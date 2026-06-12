"""
Local mock server for restful-api.dev.

Starts an in-memory HTTP server on a random port and sets RADEV_BASE_URL so
every `radev` subprocess call in the test suite hits localhost instead of the
real API. No rate limits, no network dependency, fully deterministic.

If RADEV_BASE_URL is already set (e.g. by the benchmark runner), the fixture
skips starting a new server and reuses the existing URL.
"""
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

# Seed objects so `radev list` always returns non-empty, matching
# the shape restful-api.dev returns for its pre-populated objects.
_SEED = {
    "1": {"id": "1", "name": "Google Pixel 6 Pro",    "data": {"color": "Cloudy White", "capacity": "128 GB"}},
    "2": {"id": "2", "name": "Apple iPhone 12 Mini",  "data": {"color": "Purple",       "capacity": "64 GB"}},
    "3": {"id": "3", "name": "Samsung Galaxy Z Fold2","data": {"price": 689.99,          "color": "Brown"}},
}


class _Store:
    def __init__(self):
        self._data: dict = dict(_SEED)
        self._lock = threading.Lock()

    def list_all(self):
        with self._lock:
            return list(self._data.values())

    def get(self, obj_id: str):
        with self._lock:
            return self._data.get(str(obj_id))

    def create(self, name: str, data: dict):
        obj = {"id": str(uuid.uuid4()), "name": name, "data": data or {}}
        with self._lock:
            self._data[obj["id"]] = obj
        return obj

    def patch(self, obj_id: str, data: dict):
        with self._lock:
            obj = self._data.get(str(obj_id))
            if obj is None:
                return None
            obj["data"] = {**obj.get("data", {}), **data}
            return obj

    def delete(self, obj_id: str) -> bool:
        with self._lock:
            return self._data.pop(str(obj_id), None) is not None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

def _make_handler(store: _Store):
    class Handler(BaseHTTPRequestHandler):
        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else {}

        def _send(self, payload, status: int = 200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _obj_id(self) -> str:
            return self.path.split("/objects/", 1)[1].split("?")[0]

        def do_GET(self):
            if self.path.rstrip("/") == "/objects":
                self._send(store.list_all())
            elif "/objects/" in self.path:
                obj = store.get(self._obj_id())
                self._send(obj) if obj else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        def do_POST(self):
            if self.path.rstrip("/") == "/objects":
                b = self._body()
                self._send(store.create(b.get("name", ""), b.get("data")))
            else:
                self._send({"error": "Not found"}, 404)

        def do_PATCH(self):
            if "/objects/" in self.path:
                b = self._body()
                obj = store.patch(self._obj_id(), b.get("data", {}))
                self._send(obj) if obj else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        # Some CLI implementations use PUT for updates — accept both.
        do_PUT = do_PATCH

        def do_DELETE(self):
            if "/objects/" in self.path:
                ok = store.delete(self._obj_id())
                self._send({"message": "Object deleted successfully"}) if ok else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        def log_message(self, *_):
            pass  # suppress per-request noise

    return Handler


# ---------------------------------------------------------------------------
# Pytest fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def mock_api_server():
    """Start a local mock for restful-api.dev and point RADEV_BASE_URL at it."""
    if os.environ.get("RADEV_BASE_URL"):
        # Already set by the benchmark runner — reuse it.
        yield os.environ["RADEV_BASE_URL"]
        return

    store = _Store()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(store))
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    os.environ["RADEV_BASE_URL"] = url

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield url

    server.shutdown()
    del os.environ["RADEV_BASE_URL"]
