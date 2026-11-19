"""Minimal legacy MCP stdio prototype, offline-only. No packages, sockets or secrets."""
import json
import sys
from report_core import InvalidReport, ReportService

MAX_FRAME = 65_536
VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
TOOL = {
    'name': 'weekly_campaign_report',
    'description': 'OFFLINE PROTOTYPE ONLY. Fixed Monday-Sunday campaign clicks and cost, including VAT. '
                   'Live access is disabled. No account mutations or arbitrary requests.',
    'inputSchema': {'type': 'object', 'additionalProperties': False,
                    'required': ['dateFrom', 'dateTo'], 'properties': {
                        'dateFrom': {'type': 'string', 'pattern': '^\\d{4}-\\d{2}-\\d{2}$'},
                        'dateTo': {'type': 'string', 'pattern': '^\\d{4}-\\d{2}-\\d{2}$'}}},
    'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                    'idempotentHint': True, 'openWorldHint': False},
}

class ProtocolError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message

class Server:
    def __init__(self, service=None, tool=None):
        self.service = service or ReportService()
        self.tool = tool or TOOL
        self.server_info = {'name': 'direct-reports-offline-prototype', 'version': '0.1.0'}
        self.initialized = False
        self.ready = False

    def handle(self, message):
        identifier = None
        try:
            if type(message) is not dict or message.get('jsonrpc') != '2.0':
                raise ProtocolError(-32600, 'Invalid JSON-RPC request; batches are unsupported.')
            identifier = message.get('id')
            if 'id' in message and type(identifier) not in (str, int):
                identifier = None
                raise ProtocolError(-32600, 'Invalid request ID.')
            method = message.get('method')
            params = message.get('params', {})
            if type(method) is not str or type(params) is not dict:
                raise ProtocolError(-32600, 'Invalid method or params.')
            if 'id' not in message:
                if method == 'notifications/initialized' and self.initialized:
                    self.ready = True
                return None
            if method == 'initialize':
                version = params.get('protocolVersion')
                if version not in VERSIONS:
                    version = VERSIONS[0]
                self.initialized = True
                self.ready = False
                result = {'protocolVersion': version, 'capabilities': {'tools': {}},
                          'serverInfo': self.server_info}
            elif method == 'ping':
                result = {}
            elif not self.ready:
                raise ProtocolError(-32000, 'Initialize and send notifications/initialized first.')
            elif method == 'tools/list':
                result = {'tools': [self.tool]}
            elif method == 'tools/call':
                if set(params) - {'name', 'arguments', '_meta'} or params.get('name') != self.tool['name']:
                    raise ProtocolError(-32602, 'Unknown tool or forbidden parameter.')
                try:
                    output = self.service.run(params.get('arguments'))
                    result = {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}],
                              'isError': False}
                except InvalidReport as exc:
                    result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
            else:
                raise ProtocolError(-32601, 'Method not found.')
            return {'jsonrpc': '2.0', 'id': identifier, 'result': result}
        except ProtocolError as exc:
            return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': exc.code, 'message': exc.message}}
        except Exception:
            # Never serialize exception bodies from future transports (may contain credentials).
            return {'jsonrpc': '2.0', 'id': identifier,
                    'error': {'code': -32603, 'message': 'Internal error; no sensitive details emitted.'}}

def check_json_depth(frame):
    depth = 0
    quoted = escaped = False
    for char in frame:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > 32:
                raise ValueError('Excessive JSON nesting')
        elif char in (93, 125):
            depth -= 1


def main(inp=None, out=None, server=None):
    inp, out = inp or sys.stdin.buffer, out or sys.stdout
    server = server or Server()
    while True:
        frame = inp.readline(MAX_FRAME + 1)
        if not frame:
            return 0
        if len(frame) > MAX_FRAME:
            # Terminate instead of draining an unbounded stream or processing partial input.
            return 2
        try:
            check_json_depth(frame)
            msg = json.loads(frame)
            response = server.handle(msg)
        except (ValueError, RecursionError, UnicodeDecodeError):
            response = {'jsonrpc': '2.0', 'id': None,
                        'error': {'code': -32700, 'message': 'Invalid JSON or excessive nesting.'}}
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False) + '\n')
            out.flush()

if __name__ == '__main__':
    raise SystemExit(main())
