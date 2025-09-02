"""
A basic web browser implemented in Python that uses raw TCP connections
to send HTTP requests and receive responses.
"""

import socket
import ssl
import sys
import os


class URL:
    def __init__(self, url):
        if "://" not in url:
            # Treat as a local file path
            self.scheme = "file"
            self.host = ""
            self.port = None
            self.path = url  # use directly
            return

        self.scheme, url = url.split("://", 1)
        if self.scheme in ["http", "https"]:
            # Default ports
            self.port = 80 if self.scheme == "http" else 443

            if "/" not in url:
                url += "/"
            self.host, url = url.split("/", 1)
            self.path = "/" + url

            if ":" in self.host:
                self.host, port = self.host.split(":", 1)
                self.port = int(port)

        elif self.scheme == "file":
            self.host = ""
            self.port = None
            self.path = "/" + url.lstrip("/")  # normalise to absolute path
        else:
            raise ValueError(f"Unsupported URL scheme: {self.scheme}")

    def request(self):
        # Handle file:// URLs
        if self.scheme == "file":
            try:
                with open(self.path, "r", encoding="utf8") as f:
                    return f.read()
            except FileNotFoundError:
                return f"File not found: {self.path}"

        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )

        s.connect((self.host, self.port))

        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        headers = {
            "Host": self.host,
            "Connection": "close",
            "User-Agent": "PythonBrowser",  # change to whatever you want
        }

        request_lines = [f"GET {self.path} HTTP/1.1"]
        request_lines += [f"{key}: {value}" for key, value in headers.items()]
        request_lines.append("")  # blank line signals end of headers
        request_lines.append("")  # extra for the \r\n after headers

        request = "\r\n".join(request_lines)

        s.send(request.encode("utf8"))

        response = s.makefile("r", encoding="utf8", newline="\r\n")
        statusline = response.readline()
        version, status, explanation = statusline.split(" ", 2)

        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        content = response.read()
        s.close()

        return content


def show(body):
    in_tag = False
    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            print(c, end="")


def load(url):
    body = url.request()
    show(body)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        load(URL(sys.argv[1]))
    else:
        # fallback for testing: open a local HTML file
        load(URL("file://" + os.path.abspath("test.html")))
