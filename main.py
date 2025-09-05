"""
A basic web browser implemented in Python that uses raw TCP connections
to send HTTP requests and receive responses.
"""

import socket
import ssl

# Cache for persistent sockets
socket_cache = {}  # key: (host, port), value: socket


class URL:
    def __init__(self, url):
        self.content_length = None
        if url.startswith("view-source:"):
            self.scheme = "view-source"
            self.target = url[len("view-source:"):]
            self.host = ""
            self.port = None
            self.path = None
            return

        if url.startswith("data"):
            self.scheme = "data"
            self.host = ""
            self.port = None
            self.path = url  # use directly
            return

        if "://" not in url:
            # Treat as a local file path
            self.scheme = "file"
            self.host = ""
            self.port = None
            self.path = url
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
            self.path = "/" + url.lstrip("/")
        else:
            raise ValueError(f"Unsupported URL scheme: {self.scheme}")

    def request(self):
        # Handle view-source
        if self.scheme == "view-source":
            inner = URL(self.target)
            return inner.request()

        # Handle file:// URLs
        if self.scheme == "file":
            try:
                with open(self.path, "r", encoding="utf8") as f:
                    return f.read()
            except FileNotFoundError:
                return f"File not found: {self.path}"

        # Handle data URLs
        if self.scheme == "data":
            if "," not in self.path:
                return "Malformed data: URL"

            mediatype, data = self.path.split(",", 1)
            if mediatype.endswith(";base64"):
                import base64
                try:
                    return base64.b64decode(data).decode("utf8",
                                                         errors="replace")
                except Exception as e:
                    return f"Base64 decode error: {e}"
            else:
                return data

        # --- Persistent socket reuse ---
        key = (self.host, self.port)
        s = socket_cache.get(key)

        if s is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))

            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)

            socket_cache[key] = s

        # Send HTTP request
        headers = {
            "Host": self.host,
            "Connection": "keep-alive",
            "User-Agent": "PythonBrowser",
        }

        request_lines = [f"GET {self.path} HTTP/1.1"]
        request_lines += [f"{key}: {value}" for key, value in headers.items()]
        request_lines.append("")
        request_lines.append("")

        request = "\r\n".join(request_lines)

        try:
            s.send(request.encode("utf8"))
            response = s.makefile("rb")  # binary mode
        except (BrokenPipeError, OSError):
            # Server closed connection -> make new socket
            s.close()
            socket_cache.pop(key, None)

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            socket_cache[key] = s

            s.send(request.encode("utf8"))
            response = s.makefile("rb")

        # Parse response
        statusline = response.readline().decode("utf8")
        version, status, explanation = statusline.split(" ", 2)

        response_headers = {}
        while True:
            line = response.readline().decode("utf8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        self.content_length = response_headers.get("content-length")

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        # Read only content-length bytes if present
        if self.content_length is not None:
            length = int(self.content_length)
            content = response.read(length)
        else:
            # fallback if no length given
            content = response.read()
        return content.decode("utf8", errors="replace")

    def get_scheme(self):
        return self.scheme

def show(body):
    in_tag = False
    in_entity = False
    entity = ""
    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            if c == "&":  # start of entity
                in_entity = True
                entity = "&"
            elif in_entity:
                entity += c
                if c == ";":  # end of entity
                    if entity == "&lt;":
                        print("<", end="")
                    elif entity == "&gt;":
                        print(">", end="")
                    else:
                        print(entity, end="")  # unknown entity, print as-is
                    in_entity = False
                    entity = ""
            else:
                print(c, end="")


def load(url):
    body = url.request()
    if url.get_scheme() == "view-source":
        print(body)
    else:
        show(body)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Allow data scheme inputs to have spaces by joining argv parts
        url_string = " ".join(sys.argv[1:])
        load(URL(url_string))

    else:
        import os
        # fallback for testing: open a local HTML file
        load(URL("file://" + os.path.abspath("test.html")))
