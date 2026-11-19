import io
import json
import socket
import unittest
from unittest.mock import patch
from report_core import *
from server import Server, main, MAX_FRAME

ARGS = {'dateFrom': '2026-11-09', 'dateTo': '2026-11-15'}
HEADER = b'CampaignId\tCampaignName\tClicks\tCost\n'
SYNTHETIC = HEADER + b'1001\tSYNTHETIC_A\t10\t100.90\n1002\tSYNTHETIC_B\t20\t200.90\n'

class FixtureTransport:
    def fetch(self, request):
        self.last = request
        return SYNTHETIC

class CoreTests(unittest.TestCase):
    def test_fixed_report_endpoint_method_fields(self):
        r = build_request(ARGS)
        self.assertEqual(r['endpoint'], ENDPOINT)
        self.assertEqual(r['body']['params']['IncludeVAT'], 'YES')
        self.assertEqual(r['body']['params']['FieldNames'], FIELDS)
        self.assertEqual(r['body']['params']['ReportType'], 'CAMPAIGN_PERFORMANCE_REPORT')
        self.assertNotIn('Authorization', r['headers'])

    def test_dates_and_extra_keys(self):
        bad = [None, [], {}, {'dateFrom': 20261109, 'dateTo': '2026-11-15'},
               {'dateFrom': '2026-11-10', 'dateTo': '2026-11-16'},
               {'dateFrom': '2026-11-09', 'dateTo': '2026-11-22'},
               {'dateFrom': '2026-02-30', 'dateTo': '2026-03-06'},
               {**ARGS, 'url': 'https://attacker.invalid'}, {**ARGS, 'method': 'delete'},
               {**ARGS, 'client_login': 'other-account'}, {**ARGS, 'includeVat': True}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(InvalidReport):
                build_request(value)

    def test_decimal_aggregate_before_truncation(self):
        r = parse_report(SYNTHETIC)
        self.assertEqual(r['totals'], {'clicks': 30, 'costExact': '301.80', 'costWholeUnits': 301})
        self.assertEqual(sum(x['costWholeUnits'] for x in r['rows']), 300)

    def test_large_id_preserved(self):
        r = parse_report(HEADER + b'9007199254740993\tTEST\t0\t0\n')
        self.assertEqual(r['rows'][0]['campaignId'], '9007199254740993')

    def test_empty_report(self):
        self.assertEqual(parse_report(HEADER)['totals']['costWholeUnits'], 0)

    def test_formula_is_only_inert_text(self):
        r = parse_report(HEADER + b'1\t=HYPERLINK("https://invalid")\t1\t1\n')
        self.assertTrue(r['rows'][0]['campaignName'].startswith('='))
        self.assertIn('untrusted', r['note'])

    def test_no_partial_results(self):
        bad = [b'', b'bad header\n', HEADER + b'1\tX\t1\tNaN\n',
               HEADER + b'1\tX\t1\tInfinity\n', HEADER + b'1\tX\t1\t-1\n',
               HEADER + b'1\tX\t1\t1e1000000\n', HEADER + b'1\tX\t1.2\t1\n',
               HEADER + b'1\tX\t1\t1\n1\tX\t1\t1\n',
               HEADER + b'1\tX\t1\t1\textra\n', b'\xff', b'x' * (MAX_REPORT_BYTES+1)]
        for raw in bad:
            with self.subTest(raw=raw[:40]), self.assertRaises(InvalidReport):
                parse_report(raw)

    def test_row_limit(self):
        body = HEADER + b''.join(f'{n}\tTEST\t1\t1\n'.encode() for n in range(MAX_ROWS+1))
        with self.assertRaises(InvalidReport):
            parse_report(body)

    def test_default_no_live_access(self):
        with self.assertRaisesRegex(InvalidReport, 'LIVE_ACCESS_DISABLED'):
            ReportService().run(ARGS)

    def test_synthetic_provenance(self):
        r = ReportService(FixtureTransport()).run(ARGS)
        self.assertIn('not Yandex account data', r['provenance'])

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.s = Server(ReportService(FixtureTransport()))
    def call(self, method, params=None):
        return self.s.handle({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})
    def ready(self):
        self.call('initialize', {'protocolVersion': '2025-11-25'})
        self.s.handle({'jsonrpc':'2.0','method':'notifications/initialized'})

    def test_handshake_required(self):
        self.assertIn('error', self.call('tools/list'))

    def test_one_tool_only(self):
        self.ready()
        tools = self.call('tools/list')['result']['tools']
        self.assertEqual([t['name'] for t in tools], ['weekly_campaign_report'])
        self.assertTrue(tools[0]['annotations']['readOnlyHint'])

    def test_write_and_raw_forbidden(self):
        self.ready()
        for name in ['raw_request', 'update_campaign', 'finish_login', 'get_balance']:
            self.assertIn('error', self.call('tools/call', {'name': name, 'arguments': ARGS}))

    def test_offline_tools_call(self):
        self.ready()
        r = self.call('tools/call', {'name':'weekly_campaign_report', 'arguments':ARGS})
        self.assertFalse(r['result']['isError'])

    def test_bad_arguments_tool_error(self):
        self.ready()
        r = self.call('tools/call', {'name':'weekly_campaign_report', 'arguments': {**ARGS, 'token':'fake'}})
        self.assertTrue(r['result']['isError'])

    def test_batch_and_bad_id(self):
        self.assertIn('error', self.s.handle([]))
        self.assertIn('error', self.s.handle({'jsonrpc':'2.0','id':True,'method':'ping'}))

    def test_unknown_notification_ignored(self):
        self.assertIsNone(self.s.handle({'jsonrpc':'2.0','method':'notifications/unrecognized'}))

    def test_stdio_parse_errors(self):
        out=io.StringIO()
        self.assertEqual(main(io.BytesIO(b'not-json\n'),out),0)
        self.assertEqual(json.loads(out.getvalue())['error']['code'],-32700)

    def test_deep_json_bounded(self):
        out=io.StringIO()
        main(io.BytesIO(b'['*2000+b']'*2000+b'\n'),out)
        self.assertEqual(json.loads(out.getvalue())['error']['code'],-32700)

    def test_oversize_frame_terminates(self):
        out=io.StringIO()
        self.assertEqual(main(io.BytesIO(b'x'*(MAX_FRAME+1)),out),2)
        self.assertEqual(out.getvalue(),'')

    def test_safe_exception(self):
        class Broken:
            def run(self,args):raise RuntimeError('SECRET_MUST_NOT_LEAK')
        self.ready(); self.s.service=Broken()
        r=self.call('tools/call',{'name':'weekly_campaign_report','arguments':ARGS})
        self.assertNotIn('SECRET_MUST_NOT_LEAK',json.dumps(r))

if __name__ == '__main__':
    # Deny networking even if future code accidentally introduces a network path.
    with patch.object(socket, 'socket', side_effect=AssertionError('NETWORK FORBIDDEN IN TESTS')):
        unittest.main(verbosity=2)
