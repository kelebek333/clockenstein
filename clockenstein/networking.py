import http.client
import io
import os
from types import SimpleNamespace

import httplib2
import pycurl
import requests
from requests.adapters import BaseAdapter
from requests.cookies import extract_cookies_to_jar
from requests.structures import CaseInsensitiveDict
from requests.utils import (DEFAULT_CA_BUNDLE_PATH, get_encoding_from_headers,
                            get_environ_proxies, select_proxy)

class _ResponseBody(io.BytesIO):
    def __init__(self, content, headers):
        super().__init__(content)
        # Requests reads these headers when handling cookies, including on
        # redirects and Digest authentication retries.
        self._original_response = SimpleNamespace(msg=headers)

    def release_conn(self):
        self.close()


class GoogleHttp:
    """The httplib2 interface expected by Google's authorization/API clients."""

    def __init__(self):
        self.connection = pycurl.Curl()

    def close(self):
        self.connection.close()

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        proxy = select_proxy(uri, get_environ_proxies(uri))
        try:
            status, reason, response_headers, content = _perform_request(
                self.connection, uri, method, body, headers, proxy=proxy)
        except pycurl.error as exc:
            raise httplib2.HttpLib2Error(str(exc)) from exc
        headers = _get_response_headers(response_headers)
        headers["status"] = str(status)
        response = httplib2.Response(headers)
        response.reason = reason
        return response, content


class CalDAVAdapter(BaseAdapter):
    """Requests adapter; leave CalDAV authentication, cookies and redirects to Requests."""

    def __init__(self):
        self.connection = pycurl.Curl()

    def close(self):
        self.connection.close()

    def send(self, request, stream=False, timeout=20, verify=True, cert=None, proxies=None):
        proxy = select_proxy(request.url, proxies or {})
        try:
            status, reason, response_headers, content = _perform_request(
                self.connection, request.url, request.method, request.body,
                request.headers, timeout=timeout, verify=verify, cert=cert, proxy=proxy)
        except pycurl.error as exc:
            if exc.args[0] == pycurl.E_OPERATION_TIMEDOUT:
                raise requests.Timeout(str(exc), request=request) from exc
            elif exc.args[0] in (pycurl.E_PEER_FAILED_VERIFICATION, pycurl.E_SSL_CONNECT_ERROR,
                                 pycurl.E_SSL_CACERT_BADFILE, pycurl.E_SSL_CERTPROBLEM):
                raise requests.exceptions.SSLError(str(exc), request=request) from exc
            else:
                raise requests.ConnectionError(str(exc), request=request) from exc

        response = requests.Response()
        response.status_code = status
        response.headers = CaseInsensitiveDict(_get_response_headers(response_headers))
        response.encoding = get_encoding_from_headers(response.headers)
        response.reason = reason
        response.url = request.url
        response.request = request
        response.connection = self
        response.raw = _ResponseBody(content, response_headers)
        extract_cookies_to_jar(response.cookies, request, response.raw)
        return response


def _get_response_headers(headers):
    result = {}
    for name, value in headers.items():
        name = name.lower()
        if name in result:
            result[name] += ", " + value
        else:
            result[name] = value
    return result


def _perform_request(connection, url, method, body=None, headers=None,
                     timeout=20, verify=True, cert=None, proxy=None):
    """Perform one buffered request using a reusable curl connection.

    pycurl.Curl() tries both IPv6 and IPv4 automatically.
    If IPv6 hasn’t connected after 200 ms, it starts an IPv4 connection attempt.
    Whichever succeeds gets used.
    That behavior is built into connection.perform()
    
    Do not follow redirects here.
    CalDAV's Requests session handles them.
    Google's adapter returns the redirect response without following it.
    """
    content = io.BytesIO()
    header_lines = io.BytesIO()
    reason = ""

    def receive_header(line):
        nonlocal reason
        if line.startswith(b"HTTP/"):
            # A proxy tunnel or 100 Continue can precede the final response.
            header_lines.seek(0)
            header_lines.truncate()
            status_line = line.decode("iso-8859-1").strip().split(" ", 2)
            reason = status_line[2] if len(status_line) == 3 else ""
        else:
            header_lines.write(line)
        return len(line)

    try:
        connection.setopt(pycurl.URL, url)
        connection.setopt(pycurl.PROTOCOLS, pycurl.PROTO_HTTP | pycurl.PROTO_HTTPS)
        connection.setopt(pycurl.NOSIGNAL, 1)
        connection.setopt(pycurl.TIMEOUT_MS, int(timeout * 1000) if timeout else 0)
        connection.setopt(pycurl.ACCEPT_ENCODING, "")
        request_headers = [f"{name}: {value}" for name, value in (headers or {}).items()]
        connection.setopt(pycurl.HTTPHEADER, request_headers)
        connection.setopt(pycurl.HEADERFUNCTION, receive_header)
        connection.setopt(pycurl.WRITEFUNCTION, content.write)

        # The caller has already applied environment proxy/no_proxy settings.
        # An empty proxy stops curl from applying its own environment rules.
        connection.setopt(pycurl.PROXY, proxy or "")
        connection.setopt(pycurl.NOPROXY, "")
        connection.setopt(pycurl.SSL_VERIFYPEER, bool(verify))
        connection.setopt(pycurl.SSL_VERIFYHOST, 2 if verify else 0)
        if verify:
            ca_path = DEFAULT_CA_BUNDLE_PATH if verify is True else verify
            ca_option = pycurl.CAPATH if os.path.isdir(ca_path) else pycurl.CAINFO
            connection.setopt(ca_option, ca_path)
        if cert:
            if isinstance(cert, str):
                connection.setopt(pycurl.SSLCERT, cert)
            else:
                connection.setopt(pycurl.SSLCERT, cert[0])
                connection.setopt(pycurl.SSLKEY, cert[1])

        if body is not None:
            if hasattr(body, "read"):
                body = body.read()
            if isinstance(body, str):
                body = body.encode("utf-8")
            connection.setopt(pycurl.POSTFIELDS, body)
        if method == "HEAD":
            connection.setopt(pycurl.NOBODY, True)
        connection.setopt(pycurl.CUSTOMREQUEST, method)
        connection.perform()

        status = connection.getinfo(pycurl.RESPONSE_CODE)
        header_lines.seek(0)
        response_headers = http.client.parse_headers(header_lines)
        return status, reason, response_headers, content.getvalue()
    finally:
        # Clear request options and credentials, but keep reusable connections.
        connection.reset()
