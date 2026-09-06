"""Container-side explicit submission client. The host selects and freezes the file."""

import json
import socket

with socket.socket(socket.AF_UNIX) as connection:
    connection.connect("/protocol/control.sock")
    connection.sendall(b'{"action":"submit"}\n')
    response = connection.makefile("rb").readline(4096)
    receipt = json.loads(response)
    print(json.dumps(receipt), flush=True)
    raise SystemExit(0 if receipt["accepted"] else 1)
