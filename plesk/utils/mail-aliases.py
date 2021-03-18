
import os
import argparse
import http.client 
import ssl
import lxml
import lxml.etree


PROGRAM_DESCRIPTION = "Manager e-mail aliases via plesk"


class PleskApiClient:
    """
    Client for the XML-RPC API of Plesk
    """

    def __init__(self, host, port = 8443, ssl_unverified = False):
        self.host = host
        self.port = port
        self.secret_key = None
        self.ssl_unverified = ssl_unverified

    def set_credentials(self, login, password):
        self.login = login
        self.password = password

    def set_secret_key(self, secret_key):
        self.secret_key = secret_key

    def request(self, request):
        headers = {}
        headers["Content-type"] = "text/xml"
        headers["HTTP_PRETTY_PRINT"] = "TRUE"

        if self.secret_key:
            headers["KEY"] = self.secret_key
        else:
            headers["HTTP_AUTH_LOGIN"] = self.login
            headers["HTTP_AUTH_PASSWD"] = self.password

        if self.ssl_unverified == True:
            print("Warning: Skipping certificate verification!")
            conn = httplib.HTTPSConnection(self.host, self.port, context=ssl._create_unverified_context())
        else:
            conn = http.client.HTTPSConnection(self.host, self.port)

        conn.request("POST", "/enterprise/control/agent.php", request, headers)
        response = conn.getresponse()

        return response.read()

class PleskMailAliasManager:
    """
    Manager for mail aliases
    """

    def __init__(self, client, site):
        self._client = client
        self._site = site
        self._site_id = self._get_site_id()

    def _xml_packet(self, str):
        return f"<packet>{str}</packet>"

    def _verify_status_ok(self, path, response):
        result = response.findall(f"{path}/status")
        if 1 != len(result):
            return False    # Unexpected output

        return ("ok" == result[0].text)

    def _get_site_id(self):
        request = self._xml_packet(f"""\
<site>
    <get>
    <filter>
        <name>{self._site}</name>
    </filter>
    <dataset>
        <gen_info/>
    </dataset>
    </get>
</site>\
""")

        resp = self._client.request(request)
        response = lxml.etree.XML(resp)

        site_id = None
        
        for result in response.findall("./site/get/result"):
            if not self._verify_status_ok(".", result):
                raise Exception(f"XML RPC response was not okay: '{resp}'")

            x = result.findall("./data/gen_info/name")
            assert 1 == len(x)
            assert self._site == x[0].text
        
            x = result.findall("./id")
            assert 1 == len(x)
            site_id = x[0].text

        if site_id is None:
            raise Exception(f"XML RPC response was not okay: '{resp}'")

        return int(site_id)

    def _xml_mail_packet(self, str):
        return self._xml_packet(f"<mail>{str}</mail>")

    def _xml_mail_filter_site_account_alias(self, account, alias):
        return f"""\
<filter>
    <site-id>{self._site_id}</site-id>
    <mailname>
        <name>{account}</name>
        <alias>{alias}</alias>
    </mailname>
</filter>\
"""

    def add_mail_alias(self, account, alias):
        request = self._xml_mail_packet(f"""\
<update>
    <add>
        {self._xml_mail_filter_site_account_alias(account, alias)}
    </add>
</update>\
""")

        resp = self._client.request(request)
        response = lxml.etree.XML(resp)

        if not self._verify_status_ok("./mail/update/add/result", response):
            raise Exception(f"XML RPC response was not okay: '{resp}'")

    def del_mail_alias(self, account, alias):
        request = self._xml_mail_packet(f"""\
<update>
    <remove>
        {self._xml_mail_filter_site_account_alias(account, alias)}
    </remove>
</update>\
""")

        resp = self._client.request(request)
        response = lxml.etree.XML(resp)

        if not self._verify_status_ok("./mail/update/remove/result", response):
            raise Exception(f"XML RPC response was not okay: '{resp}'")

    def query_aliases(self, account):
        request = self._xml_mail_packet(f"""\
<get_info>
    <filter>
        <site-id>{self._site_id}</site-id>
        <name>{account}</name>
    </filter>
    <aliases/>
</get_info>\
""")

        resp = self._client.request(request)
        response = lxml.etree.XML(resp)

        if not self._verify_status_ok("./mail/get_info/result", response):
            raise Exception(f"XML RPC response was not okay: '{resp}'")

        aliases = []
        for result in response.findall("./mail/get_info/result/mailname"):
            for alias in result.findall("./alias"):
                aliases.append(alias.text)

        return aliases

def parse_cmdline_args():
    p = argparse.ArgumentParser(description=PROGRAM_DESCRIPTION)

    p.add_argument("-U", dest="api_user", default="admin",
                    help="User for API access (default: 'admin')")
    p.add_argument("-H", dest="api_host", required=True, 
                    help="API endpoint host")
    p.add_argument("-P", dest="passwd_env_var", required=True, 
                    help="Environment variable that stores the API password")

    p.add_argument("-M", dest="account", required=True, 
                    help="Mail account in the form [account]@[domain]")

    p.add_argument("-L", dest="list", action="store_true", default=False,
                    help="List mail aliases")
    p.add_argument("-A", dest="add",
                    help="Add the new alias")
    p.add_argument("-R", dest="remove",
                    help="Remove the alias")

    return p, p.parse_args()

if "__main__" == __name__:
    p, args = parse_cmdline_args()

    if not args.list and args.add is None and args.remove is None:
        p.error("Either -L, -A or -R are requried")

    p = args.account.split("@")
    if not 2 == len(p):
        p.error("-M argument must be passed in the form [account]@[domain]")
    account, site = tuple(p)

    password = os.getenv(args.passwd_env_var)
    if not password:
        raise Exception(f"Failed to read value of environment variable '{args.passwd_env_var}")

    client = PleskApiClient(args.api_host)
    client.set_credentials(args.api_user, password)
    mgr = PleskMailAliasManager(client, site)

    if args.list:
        aliases = mgr.query_aliases(account)
        print("aliases:")
        for alias in aliases:
            print(f"  - {alias}")
    if args.add:
        mgr.add_mail_alias(account, args.add)
    if args.remove:
        mgr.del_mail_alias(account, args.remove)
