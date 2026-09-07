"""Exercise the public submission protocol; this rectangle is not a solved task."""

import json
import subprocess
from pathlib import Path

from klayout import db

task = json.loads(Path("/protocol/task.json").read_text())
print(Path("/protocol/prompt.txt").read_text(), flush=True)
layout = db.Layout()
top = layout.create_cell(task["output"]["top_cell"])
top.shapes(layout.layer(8, 0)).insert(db.DBox(0, 0, 1, 1))
output = Path(task["output"]["path"])
output.parent.mkdir(parents=True, exist_ok=True)
layout.write(str(output))
subprocess.run(["python", "-I", "/protocol/submit.py"], check=True)
