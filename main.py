"""
A basic web browser implemented in Python that uses raw TCP connections
to send HTTP requests and receive responses.
"""

import socket
import ssl
import tkinter


WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100


# Cache for persistent sockets
socket_cache = {}  # key: (host, port), value: socket


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT
        )
        self.canvas.pack()
        self.scroll = 0
        self.window.bind("<Down>", self.scrolldown)

    def draw(self):
        self.canvas.delete("all")
        for x, y, c in self.display_list:
            self.canvas.create_text(x, y - self.scroll, text=c)

    def load(self, url):
        """body = url.request()

        if url.get_scheme() == "view-source":
            text = body
        else:
            text = lex(body)

        self.display_list = layout(text)
        self.draw()"""

        body = url.request()
        text = lex(body)
        self.display_list = layout(text)
        self.draw()

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
        self.draw()


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

    def request(self, max_redirects=5):
        redirects = 0
        url = self
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

        while redirects < max_redirects:
            # --- Persistent socket reuse ---
            key = (url.host, url.port)
            s = socket_cache.get(key)

            if s is None:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((url.host, url.port))

                if url.scheme == "https":
                    ctx = ssl.create_default_context()
                    s = ctx.wrap_socket(s, server_hostname=url.host)

                socket_cache[key] = s

            # Send HTTP request
            headers = {
                "Host": url.host,
                "Connection": "keep-alive",
                "User-Agent": "PythonBrowser",
            }

            request_lines = [f"GET {url.path} HTTP/1.1"]
            request_lines += [f"{key}: {value}" for key, value in
                              headers.items()]
            request_lines.append("")
            request_lines.append("")

            request = "\r\n".join(request_lines)

            try:
                s.send(request.encode("utf8"))
                response = s.makefile("rb")  # binary mode
            except (BrokenPipeError, OSError):
                # Server closed connection -> make new socket
                try:
                    s.close()
                except OSError:
                    pass
                socket_cache.pop(key, None)

                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((url.host, url.port))
                if url.scheme == "https":
                    ctx = ssl.create_default_context()
                    s = ctx.wrap_socket(s, server_hostname=url.host)
                socket_cache[key] = s

                s.send(request.encode("utf8"))
                response = s.makefile("rb")

            # Parse response
            statusline = response.readline().decode("utf8")
            version, status, explanation = statusline.split(" ", 2)
            status = int(status)

            response_headers = {}
            while True:
                line = response.readline().decode("utf8")
                if line == "\r\n":
                    break
                header, value = line.split(":", 1)
                response_headers[header.casefold()] = value.strip()

            self.content_length = response_headers.get("content-length")

            # --- redirect handling (robust) ---
            if 300 <= status < 400 and "location" in response_headers:
                location = response_headers["location"]

                # If Content-Length known, drain those bytes so socket is clean
                # drain anybody if Content-Length known
                if self.content_length is not None:
                    try:
                        _ = response.read(int(self.content_length))
                    except (OSError, ValueError):
                        pass  # ignore read errors

                # close response
                try:
                    response.close()
                except (OSError, ValueError):
                    pass

                # shutdown and close socket
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # socket might already be closed
                try:
                    s.close()
                except OSError:
                    pass

                # remove from cache
                socket_cache.pop(key, None)

                # Resolve Location:
                # - absolute (http(s)://...)
                # - scheme-relative (//host/path)
                # - absolute-path (/path)
                # - relative (index.html or ../x)
                if location.startswith("http://") or location.startswith(
                        "https://"):
                    url = URL(location)
                elif location.startswith("//"):
                    # keep current scheme
                    url = URL(f"{url.scheme}:{location}")
                elif location.startswith("/"):
                    url = URL(f"{url.scheme}://{url.host}{location}")
                else:
                    # relative path resolution (use posixpath for URL paths)
                    import posixpath
                    base_dir = posixpath.dirname(url.path)
                    # ensure base_dir ends with '/'
                    if not base_dir.endswith("/"):
                        base_dir = base_dir + "/"
                    new_path = posixpath.normpath(
                        posixpath.join(base_dir, location))
                    if not new_path.startswith("/"):
                        new_path = "/" + new_path
                    url = URL(f"{url.scheme}://{url.host}{new_path}")

                redirects += 1
                continue  # follow the redirect with the new url

            # --- not a redirect: read body normally ---
            assert "transfer-encoding" not in response_headers
            assert "content-encoding" not in response_headers

            # Read only content-length bytes if present
            if self.content_length is not None:
                length = int(self.content_length)
                content = response.read(length)
            else:
                # fallback if no length given: read until connection closed by
                # server, then drop socket from cache (server will close for us)
                content = response.read()
                try:
                    response.close()
                except OSError:
                    pass
                try:
                    s.close()
                except OSError:
                    pass
                socket_cache.pop(key, None)

            return content.decode("utf8", errors="replace")

        return "Too many redirects"

    def get_scheme(self):
        return self.scheme


def lex(body):
    text = ""
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
                    text += entity
                    in_entity = False
                    entity = ""
            else:
                text += c
    return text


def layout(text):
    display_list = []
    cursor_x, cursor_y = HSTEP, VSTEP
    for c in text:
        display_list.append((cursor_x, cursor_y, c))
        cursor_x += HSTEP
        if cursor_x >= WIDTH - HSTEP:
            cursor_y += VSTEP
            cursor_x = HSTEP

    return display_list


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url_string = " ".join(sys.argv[1:])
        Browser().load(URL(sys.argv[1]))
        tkinter.mainloop()

    else:
        import os
        Browser().load(URL("file://" + os.path.abspath("test.html")))
