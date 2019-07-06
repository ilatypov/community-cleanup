#! /usr/bin/python3
# vim: et:ts=4:sts=4:sw=4:fileencoding=utf-8
r"""
Usage:

    {script} [-t] [--product PRODUCT] [--country COUNTRY] [--component COMPONENT] [--macro MACRO]

e.g.,

    {script} -t --product MikroTik --country CA --component coinhive

    {script} -t --product AVTech --country CA --macro {WEAK_AVTECH}
{message}
"""

from urllib import request, parse
from urllib.error import HTTPError, URLError
import ssl
import json
import base64
import time
from pprint import pformat
from ipaddress import ip_address
import struct, socket, sys, os
import smtplib
from email.mime.text import MIMEText


SEND_PAGES = 3
WEAK_AVTECH = "weak_avtech"


class Usage(SystemExit):
    def __init__(self, message=None):
        super(Usage, self).__init__(__doc__.format(script=os.path.basename(__file__),
            WEAK_AVTECH=WEAK_AVTECH,
            message=("\nError: %s\n" % (message,) if message else "")))


def process_http_error(e, quiet=False):
    try:
        body = e.read().decode("utf-8", errors="replace")
    except (HTTPError,) + NETWORK_ERRORS as e2:
        body = ""
        sys.stderr.write("  *** HTTP response to {url}: code {code}, body unavailable due to {classname}\n".format(url=e.geturl(),
                code=e.getcode(), classname=e2.__class__.__name__))
    else:
        if not quiet:
            sys.stderr.write("  *** HTTP response to {url}: code {code}, body {body!r}...\n".format(url=e.geturl(), 
                    code=e.getcode(), body=body[:20]))
    return body


URL_TIMEOUT = 5
REPEAT_SLEEP = 5
NETWORK_ERRORS = (socket.timeout, ConnectionRefusedError, ConnectionResetError, URLError, OSError)
def log_network_error(e, url):
    sys.stderr.write("  *** Network {classname} with {url}\n".format(classname=e.__class__.__name__,
        url=url))


def sleep_with_banner(repeatsleep):
    sys.stderr.write("  *** Repeating in {repeatsleep}s...\n".format(repeatsleep=repeatsleep))
    time.sleep(repeatsleep)


def info_shodan(testing, **kwargs):
    sys.stderr.write("Inquiring shodan.io on API usage limits...\n")

    handler = request.HTTPSHandler(debuglevel=kwargs.get("debuglevel", 0))
    opener = request.build_opener(handler)

    repeatsleep = kwargs.get("repeatsleep", REPEAT_SLEEP)
    url = "https://api.shodan.io/api-info"

    if testing:
        return {"https": False,
			 "monitored_ips": 8586,
			 "plan": "dev",
			 "query_credits": 10,
			 "scan_credits": 100,
			 "telnet": False,
			 "unlocked": True,
			 "unlocked_left": 10,
			 "usage_limits": {"monitored_ips": 16,
							  "query_credits": 100,
							  "scan_credits": 100}}

    with open(os.path.expanduser("~/.shodan")) as f:
        shodan_key = f.read().strip()

    while True:
        try:
            with opener.open(request.Request(url,
                parse.urlencode((
                        ("key", shodan_key),
                    )).encode("ascii")), timeout=URL_TIMEOUT) as response:
                if response.getcode() != 200:
                    body = process_http_error(response)
                else:
                    return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            body = process_http_error(e)
        except NETWORK_ERRORS as e:
            log_network_error(e, url)
        sleep_with_banner(repeatsleep)


def search_shodan(testing, page, **kwargs):
    argsmap = (
            ("product", "product"),
            ("component", "http.component"),
            ("country", "country"),
        )
    queryargs = []
    for (funcarg, shodanarg) in argsmap:
        if kwargs.get(funcarg) is not None:
            queryargs.append("{key}:{value}".format(key=shodanarg, value=kwargs[funcarg].lower()))
    query = " ".join(queryargs)
    sys.stderr.write("Inquiring shodan.io with \"%s\" (page %d)...\n" % (query, page,))

    handler = request.HTTPSHandler(debuglevel=kwargs.get("debuglevel", 0))
    opener = request.build_opener(handler)

    repeatsleep = kwargs.get("repeatsleep", REPEAT_SLEEP)
    url = "https://api.shodan.io/shodan/host/search"

    if testing:
        if page > 1:
            return {"matches": []}

        if kwargs.get("product", "").lower() == "mikrotik":
            return {"matches": [{
                        "product": "MikroTik http proxy",
                        "ip": 2917626385,
                        "port": 8080
                        }, {
                        "product": "MikroTik http proxy",
                        "ip": 3494743649,
                        "port": 8080
                        }]}
        elif kwargs.get("product", "").lower() == "avtech":
            return {"matches": [{
                    "product": "Avtech AVN801 network camera",
                    "ip": 1805602870,
                    "port": 88
                }, {
                    "product": "Avtech AVN801 network camera",
                    "ip": 412990438,
                    "port": 8888
                    }]}
        else:
            raise Usage("Only MikroTik and AVTech products are mocked for Shodan")

    with open(os.path.expanduser("~/.shodan")) as f:
        shodan_key = f.read().strip()

    while True:
        try:
            with opener.open(request.Request(url,
                parse.urlencode((
                        ("key", shodan_key),
                        ("query", query),
                        ("page", page),
                    )).encode("ascii")), timeout=URL_TIMEOUT) as response:
                if response.getcode() != 200:
                    body = process_http_error(response)
                else:
                    return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            body = process_http_error(e)
        except NETWORK_ERRORS as e:
            log_network_error(e, url)
        sleep_with_banner(repeatsleep)


def whoseip(ip, whoserole, debuglevel=0):
    r"""
    Obtain email addresses of a given role for the given IP address.

    >>> whoseip('71.17.138.152', 'abuse')
    ['abuse@sasktel.net']

    >>> whoseip('109.87.56.48', 'abuse')
    ['noc@triolan.com']

    >>> whoseip('76.67.127.81', 'abuse')
    ['abuse@sympatico.ca', 'abuse@bell.ca']
    """

    def get_roles_addresses(entities):
        er = [(e.get("roles", []), 
                dict([(k, v) for (k, obj, kind, v) in e.get("vcardArray", [None, []])[1]]))
            for e in entities]
        for e in entities:
            if "entities" in e:
                er.extend(get_roles_addresses(e["entities"]))
        return er

    handler = request.HTTPSHandler(debuglevel=debuglevel)
    opener = request.build_opener(handler)

    emails = []
    with opener.open(request.Request("https://rdap.arin.net/bootstrap/ip/%s" % (ip,))) as response:
        r = json.loads(response.read().decode("utf-8"))
        try:
            entroles = get_roles_addresses(r["entities"])
        except (KeyError, IndexError) as e:
            sys.stderr.write("  *** %s %s in %s\n" % (e.__class__.__name__, 
                    e, pformat(r)))
            return emails
        for roles, addr in entroles:
            if whoserole in roles:
                if "email" in addr:
                    emails.append(addr["email"])
    return emails


def read_sent_emails(sent_name):
    sent_emails = {}
    if os.path.exists(sent_name):
        with open(os.path.expanduser(sent_name)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                email, iptext = line.split(None, 1)
                if email.endswith(":"):
                    email = email[:-1]
                ips = []
                for ipstr in iptext.split():
                    if ipstr.endswith(","):
                        ipstr = ipstr[:-1]
                    ips.append(ip_address(ipstr))
                sent_emails[email] = ips
    return sent_emails


def write_sent_emails(testing, sent_name, sent_emails):
    if testing:
        return
    with open(os.path.expanduser(sent_name), "w") as f:
        for e in sorted(sent_emails.keys()):
            ehosts = sent_emails[e]
            f.write("%s: %s\n" % (e, ", ".join(str(ehost) for ehost in ehosts)))


def build_httpfilter(macro):
    httpfilter = []
    if macro is None:
        pass
    elif macro == WEAK_AVTECH:
        avtech_path = "/cgi-bin/nobody/Machine.cgi?action=get_capability"
        avtech_headers = ((b"Authentication", b"Basic %s" % (base64.b64encode(b"admin:admin"),)),)
        avtech_bodysearch = "Firmware.Version"
        httpfilter.append((avtech_path, (), avtech_bodysearch))
        httpfilter.append((avtech_path, avtech_headers, avtech_bodysearch))
    else:
        raise Usage("Unknown macro \"%s\"" % (macro,))
    return httpfilter


def check(httpfilter, baseurl, opener):
    if len(httpfilter) == 0:
        # Assume the host vulnerable in the absence of HTTP checks
        return True

    for (path_info, headers, bodysearch) in httpfilter:
        body = ""
        try:
            url = baseurl + path_info
            req = request.Request(url)
            for (name, value) in headers:
                req.add_header(name, value)
            with opener.open(req, timeout=URL_TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            body = process_http_error(e, True)
        except NETWORK_ERRORS as e:
            log_network_error(e, url)

        if bodysearch in body:
            sys.stderr.write("  *** Got {bodysearch!r} in {url}{headersinfo}\n".format(bodysearch=bodysearch, 
                url=url,
                headersinfo=(" with %s".headers[0][0] if len(headers) > 0 else "")))
            return True
    
    # sys.stderr.write("  *** No indication of vulnerabilities in %s...\n" % (url,))
    return False


def filter_hosts(infected_hosts, httpfilter, ready_emails, all_emails, debuglevel=0):
    ssl_handler = request.HTTPSHandler(debuglevel=debuglevel, context=ssl._create_unverified_context(), check_hostname=False)
    ssl_opener = request.build_opener(ssl_handler)

    plain_handler = request.HTTPHandler(debuglevel=debuglevel)
    plain_opener = request.build_opener(plain_handler)

    page_emails = {}

    for (ip, port, is_ssl) in infected_hosts:
        sys.stderr.write("%s\n" % (ip,))
        if is_ssl:
            url = "https://%s:%s" % (ip, port)
            opener = ssl_opener
        else:
            url = "http://%s:%s" % (ip, port)
            opener = plain_opener

        if check(httpfilter, url, opener):
            found_emails = False
            for e in whoseip(ip, "abuse"):
                found_emails = True
                sys.stderr.write("  %s\n" % (e,))
                page_ehosts = page_emails.get(e, [])
                ready_ehosts = ready_emails.get(e, [])
                all_ehosts = all_emails.get(e, [])
                if ip not in all_ehosts:
                    page_ehosts.append(ip)
                    ready_ehosts.append(ip)
                    all_ehosts.append(ip)
                    page_emails[e] = page_ehosts
                    ready_emails[e] = ready_ehosts
                    all_emails[e] = all_ehosts

            if not found_emails:
                sys.stderr.write("  *** No abuse notification emails found\n")

    sys.stderr.write("\n")
    for e in sorted(page_emails.keys()):
        page_ehosts = page_emails[e]
        page_ehosts.sort()
        sys.stderr.write("%s: %s\n" % (e, ", ".join(str(page_ehost) for page_ehost in page_ehosts)))

    for e in sorted(ready_emails.keys()):
        ready_ehosts = ready_emails[e]
        ready_ehosts.sort()

    for e in sorted(all_emails.keys()):
        all_ehosts = all_emails[e]
        all_ehosts.sort()


def send_mail(testing, ready_emails, myaddr, product, component, macro):
    sys.stderr.write("\n")
    prodname = product if product else "internet thing"
    if component:
        vulnerability = "running \"%s\"" % (component,)
    elif macro == WEAK_AVTECH:
        vulnerability = "missing or factory-defined authentication"
    else:
        vulnerability = "flagged by a macro %s" % (macro,)
    for e in sorted(ready_emails.keys()):
        if testing:
            sys.stderr.write("Testing email for %s by sending it just to myself...\n" % (e,))
        else:
            sys.stderr.write("Sending email to %s...\n" % (e,))
        ehosts = ready_emails[e]
        msg = MIMEText("""
Hello %s,

Your %s at the following address(es) appeared vulnerable to abuse and botnets
because of %s:

  %s

Best regards,

A community cleanup initiative
https://github.com/ilatypov/community-cleanup
""" % (e, prodname, vulnerability, "\n  ".join(str(ehost) for ehost in ehosts)))

        recipients = [myaddr]
        if not testing:
            recipients.append(e)
        msg["Subject"] = "Community cleanup: your %s needs attention" % (prodname,)
        msg["From"] = myaddr
        msg["To"] = e
        s = smtplib.SMTP("localhost")
        s.sendmail(myaddr, recipients, msg.as_string())
        s.quit()


def next_arg(argv, i):
    i += 1
    if i >= len(argv):
        raise Usage()
    return (i, argv[i])


def main(argv):
    unittesting = False
    debuglevel = 0
    testing = False
    product = None
    country = None
    component = None
    macro = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "-d":
            debuglevel = 1
        elif arg == "-t":
            testing = True
        elif arg == "-u":
            unittesting = True
        elif arg == "--product":
            i, product = next_arg(argv, i)
        elif arg == "--country":
            i, country = next_arg(argv, i)
        elif arg == "--component":
            i, component = next_arg(argv, i)
        elif arg == "--macro":
            i, macro = next_arg(argv, i)
        elif arg.startswith("-"):
            raise Usage()
        else:
            break
        i += 1

    if unittesting:
        import doctest
        (failures, tests) = doctest.testmod(verbose=(not not debuglevel))
        raise SystemExit(0 if failures == 0 else 1 + (failures % 127))

    if len(list(filter(bool, (product, country, component, macro)))) < 2:
        raise Usage("The search will benefit from using at least 2 conditions")

    httpfilter = build_httpfilter(macro)

    myaddr = "{USER}@{HOSTNAME}".format(USER=os.environ["USER"], HOSTNAME=socket.gethostname())
    sent_name = "email-hosts.txt"
    all_emails = read_sent_emails(sent_name)
    ready_emails = {}
    page = 1
    page_sender_count = 0
    while True:
        shodan_limits = info_shodan(testing, debuglevel=debuglevel)
        sys.stderr.write("Shodan limits:\n%s\n" % (pformat(shodan_limits),))

        shodan_results = search_shodan(testing, page, product=product, country=country, component=component, debuglevel=debuglevel)
        numhosts = len(shodan_results["matches"])
        sys.stderr.write("Found matches: {numhosts}\n".format(numhosts=numhosts))
        if numhosts == 0:
            break
        infected_hosts = tuple((ip_address(match["ip"]), match["port"], not not match.get("ssl")) for match in shodan_results["matches"])

        filter_hosts(infected_hosts, httpfilter, ready_emails, all_emails)
        page += 1
        page_sender_count += 1
        if page_sender_count == SEND_PAGES:
            send_mail(testing, ready_emails, myaddr, product, component, macro)
            write_sent_emails(testing, sent_name, all_emails)
            ready_emails = {}
            page_sender_count = 0

    send_mail(testing, ready_emails, myaddr, product, component, macro)
    write_sent_emails(testing, sent_name, all_emails)


if __name__ == "__main__":
    import sys
    # Wrapping parameter parsing into a function call prevents from spilling
    # them into the global namespace and accidentally using them in the other
    # functions.
    main(sys.argv)

