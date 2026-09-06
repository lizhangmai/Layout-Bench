"""Run the optional built-in CLI through the session's inference gateway."""

import http.server
import json
import os
import socket
import subprocess
import tempfile
import threading
from pathlib import Path


class Bridge(http.server.BaseHTTPRequestHandler):
    socket_path = None

    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= 8*1024*1024 or self.headers.get("Content-Encoding") or self.headers.get("Transfer-Encoding"):
                self.send_error(400)
                return
            body = self.rfile.read(size)
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(self.socket_path)
                connection.sendall(json.dumps({"path": self.path, "bytes": len(body)}).encode()+b"\n"+body)
                stream = connection.makefile("rb")
                header = json.loads(stream.readline(1025))
                self.send_response(header["status"])
                self.send_header("Content-Type", header["type"])
                self.send_header("Content-Length", str(header["bytes"]))
                self.end_headers()
                self.wfile.write(stream.read(header["bytes"]))
        except (OSError, ValueError, KeyError):
            self.close_connection = True


def main():
    profile = json.loads(Path("/protocol/inference.json").read_text())
    model = profile["model"]
    Bridge.socket_path = profile["socket"]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = {"model_provider": "layout_bench", "model_providers.layout_bench.name": "Layout-Bench",
               "model_providers.layout_bench.base_url": f"http://127.0.0.1:{server.server_port}",
               "model_providers.layout_bench.wire_api": "responses",
               "model_providers.layout_bench.requires_openai_auth": False,
               "model_providers.layout_bench.supports_websockets": False,
               "model_providers.layout_bench.request_max_retries": 0,
               "model_providers.layout_bench.stream_max_retries": 0,
               "web_search": "disabled", "features.multi_agent": False}
    arguments = [arg for key, value in options.items() for arg in ("-c", key+"="+json.dumps(value))]
    with tempfile.TemporaryDirectory(prefix=".codex-session-", dir="/workspace") as home:
        command = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
                   "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--model", model,
                   *arguments, "-"]
        result = subprocess.run(command, input=Path("/protocol/prompt.txt").read_bytes(),
                                env={**os.environ, "CODEX_HOME": home}, check=False)
    server.shutdown()
    server.server_close()
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
