"""Deterministic adapter for exercising canonical_harness, not a model score."""

import json
import sys


def response(content="", tool_calls=None, stop_reason=None):
    tool_calls = tool_calls or []
    return {
        "schema_version": 1,
        "type": "response",
        "content": content,
        "tool_calls": tool_calls,
        "stop_reason": stop_reason or ("tool_calls" if tool_calls else "stop"),
    }


def main():
    for step, line in enumerate(sys.stdin, 1):
        json.loads(line)  # The canonical harness owns the request schema.
        if step == 1:
            script = (
                "import json\n"
                "from pathlib import Path\n"
                "from klayout import db\n"
                "task = json.loads(Path('/protocol/task.json').read_text())\n"
                "layout = db.Layout()\n"
                "top = layout.create_cell(task['output']['top_cell'])\n"
                "top.shapes(layout.layer(8, 0)).insert(db.DBox(0, 0, 1, 1))\n"
                "output = Path('/workspace') / task['output']['path']\n"
                "output.parent.mkdir(parents=True, exist_ok=True)\n"
                "layout.write(str(output))\n"
            )
            calls = [{"id": "canonical-probe-write", "name": "run_command",
                      "arguments": {"argv": ["python", "-c", script]}}]
            print(json.dumps(response("Creating a deterministic rectangle.", calls)), flush=True)
        elif step == 2:
            calls = [{"id": "canonical-probe-submit", "name": "submit_layout", "arguments": {}}]
            print(json.dumps(response("Submitting the probe candidate.", calls)), flush=True)
        else:
            print(json.dumps(response("Probe complete.")), flush=True)


if __name__ == "__main__":
    main()
