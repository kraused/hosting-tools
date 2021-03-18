"""
mail-alias: Manage e-mail aliases using the Plesk XML RPC API
"""

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

    def __init__(self, host, port=8443, ssl_unverified=False):
        self.host = host
        self.port = port
        self.secret_key = None
        self.ssl_unverified = ssl_unverified
        self.login = None
        self.passwd = None

    def set_credentials(self, login, passwd):
        """Set the API user name and the password to use"""
        self.login = login
        self.passwd = passwd

    def set_secret_key(self, secret_key):
        """Specify a ssecret key to use for the API access"""
        self.secret_key = secret_key

    def request(self, request):
        """Issue the specified XML RPC request. `request` must be a valid XML string"""
        headers = {}
        headers["Content-type"] = "text/xml"
        headers["HTTP_PRETTY_PRINT"] = "TRUE"

        if self.secret_key:
            headers["KEY"] = self.secret_key
        else:
            headers["HTTP_AUTH_LOGIN"] = self.login
            headers["HTTP_AUTH_PASSWD"] = self.passwd

        if self.ssl_unverified is True:
            conn = http.client.HTTPSConnection(self.host, self.port,
                                            context=ssl._create_unverified_context())
            raise Exception("Certificate exception verification can only be "
                            "skipped by removing this exception")
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

    @classmethod
    def _xml_packet(cls, xml):
        return f"<packet>{xml}</packet>"

    @classmethod
    def _xml_find_one(cls, el, path):
        el = el.findall(path)
        if 1 != len(el):
            raise Exception("_xml_find_one() assumes that findall() returns exactly one result")
        return el[0]

    @classmethod
    def _verify_status_ok(cls, path, response):
        try:
            result = cls._xml_find_one(response, f"{path}/status")
        except Exception:
            return False

        return "ok" == result.text

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

            if self._site != self._xml_find_one(result, "./data/gen_info/name").text:
                raise Exception("XML RPC response does not match specified site name")

            site_id = int(self._xml_find_one(result, "./id").text)

        if site_id is None:
            raise Exception(f"XML RPC response was not okay: '{resp}'")

        return int(site_id)

    @classmethod
    def _xml_mail_packet(cls, xml):
        return cls._xml_packet(f"<mail>{xml}</mail>")

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
        """
        Add the specified mail alias for the account.
        """
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
        """
        Delete the specified mail alias for the account.
        """
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
        """
        List all mail aliase for the account.
        """
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
    """Parse the command line arguments"""
    p = argparse.ArgumentParser(description=PROGRAM_DESCRIPTION)

    p.add_argument("-U", dest="api_user", default="admin",
                    help="User for API access (default: 'admin')")
    p.add_argument("-H", dest="api_host", required=True,
                    help="API endpoint host")
    p.add_argument("-P", dest="passwd_env_var", required=True,
                    help="Environment variable that stores the API passwd")

    p.add_argument("-M", dest="account", required=True,
                    help="Mail account in the form [account]@[domain]")

    p.add_argument("-L", dest="list", action="store_true", default=False,
                    help="List mail aliases")
    p.add_argument("-A", dest="add",
                    help="Add the new alias")
    p.add_argument("-R", dest="remove",
                    help="Remove the alias")

    return p, p.parse_args()

def main():
    """Main program flow"""

    p, args = parse_cmdline_args()

    if not args.list and args.add is None and args.remove is None:
        p.error("Either -L, -A or -R are requried")

    p = args.account.split("@")
    if not 2 == len(p):
        p.error("-M argument must be passed in the form [account]@[domain]")
    account, site = tuple(p)

    passwd = os.getenv(args.passwd_env_var)
    if not passwd:
        raise Exception(f"Failed to read value of environment variable '{args.passwd_env_var}")

    client = PleskApiClient(args.api_host)
    client.set_credentials(args.api_user, passwd)
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

if "__main__" == __name__:
    main()
