"""Container-side optional same-semantic process-feedback client."""

import json
import socket

with socket.socket(socket.AF_UNIX) as connection:
    connection.connect("/protocol/control.sock")
    connection.sendall(b'{"action":"process_check"}\n')
    response = connection.makefile("rb").readline(16 * 1024)
    result = json.loads(response)
    print(json.dumps(result, separators=(",", ":")), flush=True)
    raise SystemExit(0 if result.get("accepted") else 1)
