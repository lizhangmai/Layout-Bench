"""Fixed-destination Responses gateway. Credentials never enter solver containers."""

import copy
import hashlib
import http.client
import json
import os
import socket
import socketserver
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .files import Asset, keys, read_file, text
from .recorder import RecordingError

MAX_BODY = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


@dataclass(frozen=True)
class InferenceConfig:
    base_url: str
    model: str
    api_key_env: str
    max_requests: int
    request_timeout_seconds: int
    source: Asset


def load_inference_config(path):
    path = path.absolute()
    source = Asset(read_file(path.parent, path.name), "toml")
    data = tomllib.loads(source.content.decode())
    keys(data, {"schema_version", "base_url", "model", "api_key_env", "max_requests",
                "request_timeout_seconds"}, set(), "inference profile")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported inference profile")
    url = urlsplit(text(data["base_url"], "inference endpoint"))
    if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query
            or url.fragment or ".." in url.path or "%" in url.path):
        raise ValueError("Inference requires a fixed HTTPS base URL without credentials, query or fragment")
    text(data["model"], "model")
    if not text(data["api_key_env"], "key environment variable").isidentifier():
        raise ValueError("Invalid credential environment variable name")
    for name in ("max_requests", "request_timeout_seconds"):
        if type(data[name]) is not int or data[name] <= 0:
            raise ValueError(f"{name} must be a positive integer")
    return InferenceConfig(*(data[k] for k in ("base_url", "model", "api_key_env", "max_requests",
                                             "request_timeout_seconds")), source)


def validate_request(path, body, model):
    if path not in {"/responses", "/responses/compact"}:
        raise ValueError("Only Responses generation and compaction are allowed")
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("model") != model:
        raise ValueError("Request model differs from the fixed profile")
    # Remote tools and externally hosted inputs bypass the declared tool environment.
    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"file_id", "file_url", "container_id"}:
                    raise ValueError("Remote resource references are disabled")
                if key == "image_url" and (not isinstance(item, str) or not item.startswith("data:")):
                    raise ValueError("Only inline images are allowed")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    def check_tools(tools):
        if not isinstance(tools, list):
            raise TypeError("Invalid tools list")
        for tool in tools:
            if not isinstance(tool, dict) or tool.get("type") not in {"function", "custom", "namespace"}:
                raise ValueError("Only client-executed tools are allowed")
            if tool["type"] == "namespace":
                check_tools(tool.get("tools", []))

    inspect(data)
    check_tools(data.get("tools", []))
    if data.get("background") or data.get("conversation") or data.get("previous_response_id"):
        raise ValueError("Only stateless foreground inference is allowed")
    if path == "/responses":
        data["store"] = False
    return json.dumps(data, separators=(",", ":")).encode()


def response_semantics(path, content_type, body):
    """Require a terminal Responses result, independently of HTTP success."""
    messages = []
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "text/event-stream":
        # SSE data fields may span lines; an unterminated frame is not a commit.
        lines, event_name = [], None
        wire = body.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        # Only CR/LF delimit SSE lines; Unicode separators may occur inside JSON strings.
        wire_lines = wire.split("\n")
        for line in wire_lines[:-1] if wire.endswith("\n") else wire_lines:
            if not line:
                if lines:
                    raw = "\n".join(lines)
                    if raw != "[DONE]":
                        message = json.loads(raw)
                        if not isinstance(message, dict) or (event_name and message.get("type") != event_name):
                            raise ValueError("Invalid SSE event")
                        messages.append(message)
                lines, event_name = [], None
            elif line.startswith("data:"):
                lines.append(line[5:].removeprefix(" "))
            elif line.startswith("event:"):
                event_name = line[6:].strip()
        if lines:
            raise ValueError("Truncated SSE frame")
        terminal = [m for m in messages if m.get("type") in {
            "response.completed", "response.failed", "response.incomplete", "error"}]
        if len(terminal) != 1 or terminal[0] is not messages[-1]:
            raise ValueError("Missing or conflicting terminal response")
        final = terminal[0]
        if final["type"] == "error":
            return {"outcome": "service_error", "reason": final.get("code"), "usage": None}
        response = final.get("response")
        if not isinstance(response, dict) or final["type"] != "response." + str(response.get("status")):
            raise ValueError("Inconsistent response terminal status")
    elif media == "application/json":
        response = json.loads(body)
        if not isinstance(response, dict):
            raise ValueError("Invalid response object")
    else:
        raise ValueError("Unsupported response media type")
    if path == "/responses/compact" and response.get("object") == "response.compaction":
        if not isinstance(response.get("output"), list) or response.get("error"):
            raise ValueError("Invalid compaction result")
        outcome, reason = "completed", None
    elif response.get("status") == "failed" or response.get("error"):
        outcome, reason = "service_error", (response.get("error") or {}).get("code")
    elif response.get("status") == "completed":
        outcome, reason = "completed", None
    elif response.get("status") == "incomplete":
        reason = (response.get("incomplete_details") or {}).get("reason")
        outcome = {"max_output_tokens": "budget_truncated", "content_filter": "content_filtered"}.get(
            reason, "incomplete_error")
    else:
        raise ValueError("Missing terminal response status")
    return {"outcome": outcome, "reason": reason, "usage": response.get("usage")}


class ResponsesGateway:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.is_test = transport is not None
        self._key = None if self.is_test else os.environ.get(config.api_key_env)
        if not self.is_test and not self._key:
            raise ValueError(f"Missing host credential environment variable: {config.api_key_env}")
        if self._key and ("\r" in self._key or "\n" in self._key):
            raise ValueError("Invalid host credential")
        self._transport = transport or self._https
        self._lock = threading.Lock()
        self._connection = None
        self._socket = None
        self.events = []
        self.denied = 0
        self.limit_reached = False
        self.deadline = 0
        self.server = None
        self.recorder = None
        self.shutdown_incomplete = False
        self._stopped = False

    @property
    def public(self):
        return {"model": self.config.model, "base_url": self.config.base_url,
                "max_requests": self.config.max_requests,
                "request_timeout_seconds": self.config.request_timeout_seconds,
                "transport": "test" if self.is_test else "https",
                "source_sha256": Asset(Path(__file__).read_bytes(), "python").sha256}

    def _https(self, path, body, timeout):
        url = urlsplit(self.config.base_url)
        request_deadline = min(self.deadline, time.monotonic() + timeout)
        connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=timeout)
        self._connection = connection
        try:
            connection.connect()
            self._socket = connection.sock
            remaining = min(self.deadline, request_deadline) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Inference deadline exceeded before sending")
            self._socket.settimeout(remaining)
            connection.request("POST", url.path.rstrip("/") + path, body=body,
                               headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                                        "Accept": "text/event-stream, application/json"})
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                return response.status, "application/json", b'{"error":"Inference upstream rejected request"}'
            result = bytearray()
            while True:
                remaining = min(self.deadline, request_deadline) - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Inference deadline exceeded")
                if self._socket:
                    self._socket.settimeout(min(timeout, remaining))
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > MAX_RESPONSE:
                    raise ValueError("Inference response exceeds size limit")
            content = bytes(result)
            if any(value in content for value in (self._key.encode(),
                    json.dumps(self._key)[1:-1].encode(), json.dumps(self._key, ensure_ascii=False)[1:-1].encode())):
                raise ValueError("Upstream response contained credential material")
            return response.status, response.getheader("Content-Type", "application/json"), content
        finally:
            connection.close()
            self._connection = None
            self._socket = None

    def _record(self, kind, **data):
        if self.recorder:
            self.recorder.event(kind, **data)

    def request(self, path, body):
        if self._stopped:
            return 429, "application/json", b'{"error":"Inference session stopped"}'
        if not self._lock.acquire(blocking=False):
            self._record("inference.denied", reason="concurrent_request")
            return 429, "application/json", b'{"error":"Concurrent inference is disabled"}'
        try:
            if self._stopped:
                return 429, "application/json", b'{"error":"Inference session stopped"}'
            if len(body) > MAX_BODY:
                self._record("inference.denied", reason="request_too_large")
                return 413, "application/json", b'{"error":"Request too large"}'
            if time.monotonic() >= self.deadline or len(self.events) >= self.config.max_requests:
                self.limit_reached = True
                self._record("inference.denied", reason="budget_exhausted")
                return 429, "application/json", b'{"error":"Inference budget exhausted"}'
            try:
                payload = validate_request(path, body, self.config.model)
            except (ValueError, TypeError, RecursionError):
                self.denied += 1
                self._record("inference.denied", reason="invalid_request")
                return 400, "application/json", b'{"error":"Request violates inference profile"}'
            event = {"path": path, "request_sha256": hashlib.sha256(payload).hexdigest(),
                     "request_bytes": len(payload), "status": None, "usage": None,
                     "sequence": len(self.events) + 1, "outcome": "pending", "started_at": time.time()}
            self.events.append(event)
            if self.recorder:
                event["request"] = self.recorder.archive(Asset(payload, "json"))
            self._record("inference.request", **event)
            try:
                status, content_type, response = self._transport(path, payload, min(
                    self.config.request_timeout_seconds, self.deadline - time.monotonic()))
                if len(response) > MAX_RESPONSE or time.monotonic() >= self.deadline:
                    raise ValueError("Response exceeded session limits")
                event.update(status=status, response_bytes=len(response), response_sha256=hashlib.sha256(response).hexdigest())
                if self.recorder:
                    event["response"] = self.recorder.archive(Asset(response, "text"))
                if 200 <= status < 300:
                    event.update(response_semantics(path, content_type, response))
                else:
                    event["outcome"] = "http_error"
                event["content_type"] = content_type
                result = status, content_type, response
            except RecordingError:
                raise
            except Exception:  # noqa: BLE001 -- never expose transport exceptions or credential-bearing bodies
                event["cancelled"] = time.monotonic() >= self.deadline
                event["status"] = 499 if event["cancelled"] else 502
                event["outcome"] = "cancelled" if event["cancelled"] else "protocol_or_transport_error"
                result = 502, "application/json", b'{"error":"Inference transport failed"}'
            event["finished_at"] = time.time()
            self._record("inference.result", **event)
            return result
        finally:
            self._lock.release()

    def start(self, path, deadline, *, uid=None):
        self.deadline = deadline
        gateway = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(2)
                try:
                    header = json.loads(self.rfile.readline(1025))
                    size = header["bytes"]
                    if type(size) is not int or not 0 <= size <= MAX_BODY:
                        return
                    body = self.rfile.read(size)
                    if len(body) != size:
                        return
                    status, kind, response = gateway.request(header["path"], body)
                    self.wfile.write(json.dumps({"status": status, "type": kind, "bytes": len(response)}).encode()+b"\n")
                    self.wfile.write(response)
                except (OSError, ValueError, KeyError, TypeError):
                    return

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
            slots = threading.BoundedSemaphore(2)

            def process_request(self, request, client_address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                super().process_request(request, client_address)

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.slots.release()

        self.server = Server(str(path), Handler)
        if uid is not None and os.getuid() == 0:
            os.chown(path, uid, -1)
        Path(path).chmod(0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()

    def stop(self):
        self._stopped = True
        self.deadline = 0
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
        # Join the request owner before reading its final semantic verdict.
        if self._lock.acquire(timeout=2):
            self._lock.release()
        else:
            self.shutdown_incomplete = True

    def summary(self):
        usage = {}
        for field in ("input_tokens", "output_tokens"):
            values = [e["usage"].get(field) if isinstance(e["usage"], dict) else None for e in self.events]
            usage[field] = sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None
        usage["cost"] = None
        for field, group, key in (("cached_input_tokens", "input_tokens_details", "cached_tokens"),
                                  ("reasoning_output_tokens", "output_tokens_details", "reasoning_tokens")):
            groups = [e["usage"].get(group) if isinstance(e["usage"], dict) else None for e in self.events]
            values = [g.get(key) if isinstance(g, dict) else None for g in groups]
            usage[field] = sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None
        return {**self.public, "requests": copy.deepcopy(self.events), "usage": usage,
                "denied_requests": self.denied, "limit_reached": self.limit_reached,
                "shutdown_incomplete": self.shutdown_incomplete,
                "infrastructure_error": self.shutdown_incomplete or any(e["outcome"] not in {"completed", "budget_truncated",
                                                                  "content_filtered", "cancelled"}
                                            for e in self.events)}
