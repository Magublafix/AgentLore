"""Stdlib stub of the two GitHub endpoints ``init`` touches: ``GET /user`` and ``GET /gists``.

Bound to 127.0.0.1 on an ephemeral port. Records every request (path, Authorization header)
so tests can assert the stub was really hit and that the token only went here.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class GithubStub:
    def __init__(self, login: str = "e2e-user") -> None:
        self.login = login
        self.mode = "ok"  # ok | 401 | 500 | delay
        self.delay = 15.0
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # silence
                pass

            def _send(self, code: int, body: object, headers: dict | None = None) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_GET(self) -> None:  # noqa: N802
                with stub._lock:
                    stub.requests.append({"method": "GET", "path": self.path.split("?")[0],
                                          "auth": self.headers.get("Authorization", "")})
                    mode = stub.mode
                if mode == "delay":
                    time.sleep(stub.delay)
                if mode == "401":
                    return self._send(401, {"message": "Bad credentials"})
                if mode == "500":
                    return self._send(500, {"message": "Server Error"})
                path = self.path.split("?")[0]
                if path == "/user":
                    return self._send(200, {"login": stub.login}, {"X-OAuth-Scopes": "gist"})
                if path == "/gists":
                    return self._send(200, [])
                self._send(404, {"message": "Not Found"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "GithubStub":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def paths(self) -> list[str]:
        with self._lock:
            return [r["path"] for r in self.requests]

    def auth_headers(self) -> set[str]:
        with self._lock:
            return {r["auth"] for r in self.requests}
