"""Provider-neutral model/tool loop for the Layout-Bench session protocol.

The harness owns the conversation and the two reviewed tools.  A model
adapter is an executable that reads one JSON request per line on stdin and
writes one normalized JSON response per line on stdout.  The adapter may use
any provider or a local model; provider-specific code stays outside this
fixed loop.
"""

from __future__ import annotations

import argparse
import json
import math
import select
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 1
MAX_ADAPTER_LINE_BYTES = 8 * 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
DEFAULT_ADAPTER_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TURNS = 64
TOOL_TIMEOUT_SECONDS = 30
SUBMISSION_TIMEOUT_SECONDS = 10
WORKSPACE = Path("/workspace")
TASK_DESCRIPTOR = Path("/protocol/task.json")
PROMPT = Path("/protocol/prompt.txt")
SUBMIT = Path("/protocol/submit.py")

TOOLS = (
    {
        "type": "function",
        "name": "run_command",
        "description": "Run one command in the writable /workspace and return bounded output.",
        "parameters": {
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": TOOL_TIMEOUT_SECONDS},
            },
            "required": ["argv"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "submit_layout",
        "description": "Submit the configured GDS path; the host returns an acceptance receipt.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)
TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _bounded_text(data):
    truncated = len(data) > MAX_TOOL_OUTPUT_BYTES
    return data[:MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="replace"), truncated


def _run_process(argv, timeout):
    """Run a command with bounded stdout/stderr and a hard local timeout."""
    process = subprocess.Popen(argv, cwd=WORKSPACE, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    streams = set(buffers)
    timed_out = output_limited = False
    deadline = time.monotonic() + timeout
    while streams:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            if process.poll() is None:
                process.kill()
            break
        ready, _, _ = select.select(list(streams), [], [], remaining)
        if not ready:
            continue
        for stream in ready:
            chunk = stream.read1(8192)
            if not chunk:
                streams.remove(stream)
                continue
            buffer = buffers[stream]
            room = max(0, MAX_TOOL_OUTPUT_BYTES - len(buffer))
            buffer.extend(chunk[:room])
            if len(chunk) > room:
                output_limited = True
                if process.poll() is None:
                    process.kill()
    if timed_out or output_limited:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stdout = _bounded_text(bytes(buffers[process.stdout]))
    stderr = _bounded_text(bytes(buffers[process.stderr]))
    process.stdout.close()
    process.stderr.close()
    return {
        "ok": process.returncode == 0 and not timed_out and not output_limited,
        "exit_code": process.returncode,
        "stdout": stdout[0],
        "stderr": stderr[0],
        "truncated": stdout[1] or stderr[1] or output_limited,
        "timed_out": timed_out,
    }


def _tool_result(name, arguments):
    if name == "run_command":
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "arguments must be an object"}
        argv = arguments.get("argv")
        if (not isinstance(argv, list) or not argv or len(argv) > 256 or
                any(not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value
                    for value in argv)):
            return {"ok": False, "error": "argv must be a nonempty list of strings"}
        timeout = arguments.get("timeout_seconds", TOOL_TIMEOUT_SECONDS)
        if (isinstance(timeout, bool) or type(timeout) not in {int, float}
                or not math.isfinite(timeout) or not 0.1 <= timeout <= TOOL_TIMEOUT_SECONDS):
            return {"ok": False, "error": f"timeout_seconds must be between 0.1 and {TOOL_TIMEOUT_SECONDS:g}"}
        try:
            return _run_process(argv, float(timeout))
        except OSError as error:
            return {"ok": False, "error": f"command could not start: {type(error).__name__}"}
    if name == "submit_layout":
        if arguments != {}:
            return {"ok": False, "error": "submit_layout takes no arguments"}
        try:
            result = _run_process([sys.executable, "-I", str(SUBMIT)], SUBMISSION_TIMEOUT_SECONDS)
        except OSError as error:
            return {"ok": False, "error": f"submission could not start: {type(error).__name__}"}
        receipt = None
        if result["stdout"]:
            try:
                receipt = json.loads(result["stdout"].strip().splitlines()[-1])
            except (TypeError, ValueError):
                pass
        return {**result, "receipt": receipt}
    return {"ok": False, "error": f"unknown tool: {name}"}


def validate_model_response(value):
    """Validate and normalize one provider-independent adapter response."""
    if not isinstance(value, dict):
        raise TypeError("Adapter response must be an object")
    allowed = {"schema_version", "type", "content", "tool_calls", "stop_reason"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Adapter response has unknown fields: {sorted(unknown)}")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("type") != "response":
        raise ValueError("Unsupported adapter response schema")
    content = value.get("content", "")
    if not isinstance(content, str):
        raise TypeError("Adapter response content must be a string")
    calls = value.get("tool_calls", [])
    if not isinstance(calls, list):
        raise TypeError("Adapter response tool_calls must be a list")
    normalized, seen = [], set()
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"id", "name", "arguments"}:
            raise ValueError("Each tool call needs id, name and arguments")
        call_id, name, arguments = call["id"], call["name"], call["arguments"]
        if (not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 256
                or call_id in seen or not isinstance(name, str) or name not in TOOL_NAMES
                or not isinstance(arguments, dict)):
            raise ValueError("Invalid or duplicate tool call")
        seen.add(call_id)
        normalized.append({"id": call_id, "name": name, "arguments": arguments})
    stop_reason = value.get("stop_reason", "tool_calls" if normalized else "stop")
    if stop_reason not in {"tool_calls", "stop", "length", "error"}:
        raise ValueError("Unknown adapter stop_reason")
    if bool(normalized) != (stop_reason == "tool_calls"):
        raise ValueError("stop_reason does not match tool_calls")
    return {"schema_version": SCHEMA_VERSION, "type": "response", "content": content,
            "tool_calls": normalized, "stop_reason": stop_reason}


class AdapterProcess:
    """One line-oriented adapter process; no shell expansion is performed."""

    def __init__(self, command, timeout=DEFAULT_ADAPTER_TIMEOUT_SECONDS):
        if not isinstance(command, (list, tuple)) or not command or any(
                not isinstance(value, str) or not value for value in command):
            raise ValueError("Adapter command must be a nonempty argument list")
        self.timeout = timeout
        self.process = subprocess.Popen(list(command), cwd=WORKSPACE, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=None)

    def request(self, value):
        encoded = _json_bytes(value) + b"\n"
        if len(encoded) > MAX_ADAPTER_LINE_BYTES:
            raise ValueError("Adapter request exceeds the size limit")
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
        except OSError as error:
            raise RuntimeError("Adapter stopped before receiving a request") from error
        ready, _, _ = select.select([self.process.stdout], [], [], self.timeout)
        if not ready:
            raise TimeoutError("Adapter response timed out")
        line = self.process.stdout.readline(MAX_ADAPTER_LINE_BYTES + 1)
        if not line:
            raise RuntimeError("Adapter stopped without a response")
        if not line.endswith(b"\n") or len(line) > MAX_ADAPTER_LINE_BYTES:
            raise ValueError("Adapter response line exceeds the size limit")
        try:
            return json.loads(line)
        except (TypeError, ValueError) as error:
            raise ValueError("Adapter response is not valid JSON") from error

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _initial_conversation(task):
    descriptor = json.dumps(task, indent=2, sort_keys=True)
    system = (
        "You are a circuit-layout agent. Work only through the supplied tools. "
        "Inspect the read-only task inputs and reviewed resources, create the requested GDS in /workspace, "
        "and call submit_layout when a candidate is ready. Do not claim success from your own checks."
    )
    user = PROMPT.read_text() + "\n\nFrozen task descriptor:\n" + descriptor
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def run(adapter_command, *, max_turns=DEFAULT_MAX_TURNS, adapter_timeout=DEFAULT_ADAPTER_TIMEOUT_SECONDS):
    if type(max_turns) is not int or not 1 <= max_turns <= 1000:
        raise ValueError("max_turns must be between 1 and 1000")
    task = json.loads(TASK_DESCRIPTOR.read_text())
    if not isinstance(task, dict):
        raise TypeError("Task descriptor must be an object")
    conversation = _initial_conversation(task)
    seen_call_ids = set()
    with AdapterProcess(adapter_command, adapter_timeout) as adapter:
        for _ in range(max_turns):
            request = {"schema_version": SCHEMA_VERSION, "type": "request",
                       "conversation": conversation, "tools": list(TOOLS)}
            response = validate_model_response(adapter.request(request))
            if response["content"]:
                print(response["content"], flush=True)
            conversation.append({"role": "assistant", "content": response["content"],
                                 "tool_calls": response["tool_calls"]})
            if not response["tool_calls"]:
                return response["stop_reason"]
            for call in response["tool_calls"]:
                if call["id"] in seen_call_ids:
                    raise ValueError("Adapter reused a tool call id")
                seen_call_ids.add(call["id"])
                result = _tool_result(call["name"], call["arguments"])
                conversation.append({"role": "tool", "tool_call_id": call["id"],
                                     "name": call["name"], "content": json.dumps(result, sort_keys=True)})
    raise TimeoutError("Canonical harness reached max_turns before the adapter stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--adapter-timeout", type=float, default=DEFAULT_ADAPTER_TIMEOUT_SECONDS)
    parser.add_argument("--adapter", nargs="+", required=True,
                        help="Adapter command; receives normalized JSONL requests")
    args = parser.parse_args()
    if (isinstance(args.adapter_timeout, bool) or not math.isfinite(args.adapter_timeout)
            or args.adapter_timeout <= 0):
        parser.error("--adapter-timeout must be a positive finite number")
    try:
        run(args.adapter, max_turns=args.max_turns, adapter_timeout=args.adapter_timeout)
    except (OSError, TypeError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
        print(f"Canonical harness stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
