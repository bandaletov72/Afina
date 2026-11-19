"""Prepared explicit local stdio integration; no network or token read at startup."""
import copy
import os
import re
import sys
from server import Server, TOOL, main
from verify_direct import identity, KNOWN_CLIENT_ID
from windows_credentials import CredentialStore
from network_adapter import FixedHTTPS, ReportsTransport
from report_core import InvalidReport, build_request, parse_report
from result_ui import report_text
import json

class WindowsReportService:
    def __init__(self, expected_client_id, expected_login, *, provider=None, http=None):
        if type(expected_client_id) is not str or not re.fullmatch(r'[0-9]{1,30}',expected_client_id):
            raise InvalidReport('Configure verified advertiser ClientId.')
        if type(expected_login) is not str or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',expected_login):
            raise InvalidReport('Configure verified Direct Login.')
        self.expected_client_id,self.expected_login=expected_client_id,expected_login
        self.provider=provider or (lambda:CredentialStore(KNOWN_CLIENT_ID).access_token())
        self.http=http or FixedHTTPS()  # caller must explicitly opt in to live
    def run(self, arguments):
        request=build_request(arguments) # reject invalid arguments before credentials/network
        try:
            token=self.provider()
            pinned=lambda:token
            account=identity(pinned,self.http)
            if account['clientId']!=self.expected_client_id or account['login']!=self.expected_login:
                raise InvalidReport('Verified account does not match configured binding.')
            result=parse_report(ReportsTransport(pinned,http=self.http).fetch(request))
            result['currency']=account['currency']
            result['period']=dict(arguments)
            output=report_text(account,result)
            if token in output: raise InvalidReport('Credential reflection rejected.')
            return json.loads(output)
        except Exception:
            raise InvalidReport('REPORT_NOT_VERIFIED: account, credential, API or report check failed; no partial data returned.') from None

def create_server(environment):
    live=environment.get('AFINA_DIRECT_LIVE')=='1'
    service=WindowsReportService(environment.get('AFINA_DIRECT_ADVERTISER_ID'),
                                 environment.get('AFINA_DIRECT_LOGIN'),
                                 http=FixedHTTPS(live_enabled=live))
    tool=copy.deepcopy(TOOL)
    tool['description']='Read-only weekly campaign clicks and costs INCLUDING VAT, Monday-Sunday. Bound to verified advertiser/user. No mutations or arbitrary API.'
    tool['annotations']['openWorldHint']=True
    server=Server(service,tool)
    server.server_info={'name':'afina-direct-reports','version':'0.2.0'}
    return server

def run():
    try:
        server=create_server(os.environ)
        if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
        return main(server=server)
    except Exception:
        # Fixed startup status, no exception/config/token contents.
        sys.stderr.write('Afina MCP startup failed: verify nonsecret account binding and Python environment.\n')
        return 1
if __name__=='__main__':
    raise SystemExit(run())
