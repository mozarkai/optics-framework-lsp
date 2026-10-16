import json
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SERVER = (
    "import sys;from optics_framework_lsp import screen;screen.LOCAL=();"
    "from optics_framework_lsp.cli import main;sys.argv=['optics-lsp'];main()"
)


def _frame(message):
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


@pytest.mark.parametrize("how", ["stdin", signal.SIGTERM, signal.SIGHUP])
def test_a_held_hub_session_is_closed_however_the_editor_stops_the_server(tmp_path, how):
    calls = []

    class Hub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, value):
            body = json.dumps({"value": value}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            calls.append("POST")
            self._reply({"sessionId": "S1", "capabilities": {}})

        def do_GET(self):
            self._reply("AAAA")

        def do_DELETE(self):
            calls.append("DELETE")
            self._reply(None)

    hub = ThreadingHTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    (tmp_path / "config.yaml").write_text(
        f"driver_sources:\n  - appium:\n      enabled: true\n      url: http://127.0.0.1:{hub.server_port}/wd/hub\n"
        "      capabilities:\n        platformName: Android\n        udid: X1\n"
    )
    (tmp_path / "e.csv").write_text("element_name,element_id\n")
    uri = tmp_path.as_uri()
    server = subprocess.Popen([sys.executable, "-c", SERVER], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    try:
        server.stdin.write(_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "processId": None, "rootUri": uri, "workspaceFolders": [{"uri": uri, "name": "w"}], "capabilities": {}}}))
        server.stdin.write(_frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        server.stdin.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "workspace/executeCommand", "params": {
            "command": "optics.remoteScreen", "arguments": [uri + "/e.csv"]}}))
        server.stdin.flush()
        deadline = time.monotonic() + 15
        while "POST" not in calls and time.monotonic() < deadline:
            time.sleep(0.1)
        assert "POST" in calls
        server.stdin.close() if how == "stdin" else server.send_signal(how)
        server.wait(15)
        assert "DELETE" in calls
    finally:
        server.kill()
        hub.shutdown()
