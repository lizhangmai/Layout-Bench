"""Host-owned provider-neutral inference gateway and wire-adapter seam.

Harnesses remain opaque to this module; they may use the selected wire family
through a small reviewed bridge of their own.
"""

import copy
import hashlib
import http.client
import json
import math
import os
import socket
import socketserver
import threading
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .files import Asset, keys, read_file, text
from .recorder import RecordingError

MAX_BODY = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
INFERENCE_SOCKET = "/protocol/inference.sock"
LEGACY_INFERENCE_SOCKET = "/protocol/model.sock"
GENERIC_HTTP_ERROR = b'{"error":"Inference upstream rejected request"}'
GENERIC_RESPONSE_ERROR = b'{"error":"Inference response failed validation"}'
USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens",
                "reasoning_output_tokens", "cost")
FAILED_OUTCOMES = frozenset({"service_error", "http_error", "protocol_or_transport_error",
                             "incomplete_error", "cancelled"})


@dataclass(frozen=True)
class InferenceConfig:
    base_url: str
    model: str
    api_key_env: str
    max_requests: int
    request_timeout_seconds: int
    source: Asset
    wire_api: str
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_wall_seconds: int | None = None


@dataclass(frozen=True)
class WireRequest:
    """Provider-wire HTTP request prepared by a registered adapter.

    ``path`` is relative to the fixed profile base URL.  An adapter may choose
    the method, path suffix, and authentication/header convention, while the
    gateway still owns the destination, body/response limits, and deadline.
    """

    method: str
    path: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class InferenceUsage:
    """Normalized observable usage shared by all wire families."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    cost: float | None = None

    def as_dict(self):
        return {field: getattr(self, field) for field in USAGE_FIELDS}


def normalize_usage(value, *, input_details=None, output_details=None):
    """Normalize adapter-specific usage to the common nullable fields.

    Missing values remain ``None``.  Invalid values are a wire-protocol error;
    the gateway never guesses a zero or fills a missing provider field.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("Inference usage must be an object")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    raw = {
        "input_tokens": value.get("input_tokens"),
        "output_tokens": value.get("output_tokens"),
        "cached_input_tokens": value.get("cached_input_tokens", input_details.get("cached_tokens")),
        "reasoning_output_tokens": value.get("reasoning_output_tokens", output_details.get("reasoning_tokens")),
        "cost": value.get("cost"),
    }
    normalized = {}
    for field, item in raw.items():
        if item is None:
            normalized[field] = None
        elif field == "cost":
            if isinstance(item, bool) or type(item) not in {int, float} or not math.isfinite(item) or item < 0:
                raise ValueError(f"Invalid usage field: {field}")
            normalized[field] = float(item)
        elif type(item) is not int or item < 0:
            raise ValueError(f"Invalid usage field: {field}")
        else:
            normalized[field] = item
    return InferenceUsage(**normalized).as_dict()


def load_inference_config(path):
    path = path.absolute()
    source = Asset(read_file(path.parent, path.name), "toml")
    data = tomllib.loads(source.content.decode())
    keys(data, {"schema_version", "base_url", "model", "api_key_env", "max_requests",
                "request_timeout_seconds", "wire_api"},
         {"max_input_tokens", "max_output_tokens", "max_wall_seconds"}, "inference profile")
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
    for name in ("max_input_tokens", "max_output_tokens", "max_wall_seconds"):
        if name in data and (type(data[name]) is not int or data[name] <= 0):
            raise ValueError(f"{name} must be a positive integer")
    wire_api = text(data["wire_api"], "inference wire_api")
    _wire_adapter(wire_api)
    return InferenceConfig(*(data[k] for k in ("base_url", "model", "api_key_env", "max_requests",
                                             "request_timeout_seconds")), source, wire_api,
                           *(data.get(k) for k in ("max_input_tokens", "max_output_tokens",
                                                   "max_wall_seconds")))


def _validate_responses_request(path, body, model):
    if path not in {"/responses", "/responses/compact"}:
        raise ValueError("Only Responses generation and compaction are allowed")
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("model") != model:
        raise ValueError("Request model differs from the fixed profile")
    # Remote resources in the model input bypass the declared tool environment.
    # Do not walk the whole request here: function-tool JSON schemas are ordinary
    # user data and may legitimately use names such as ``file_id`` or
    # ``image_url`` for their own arguments.
    def inspect_input(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"file_id", "file_url", "container_id"}:
                    raise ValueError("Remote resource references are disabled")
                if key == "image_url" and (not isinstance(item, str) or not item.startswith("data:")):
                    raise ValueError("Only inline images are allowed")
                inspect_input(item)
        elif isinstance(value, list):
            for item in value:
                inspect_input(item)

    def check_tools(tools):
        if not isinstance(tools, list):
            raise TypeError("Invalid tools list")
        for tool in tools:
            if not isinstance(tool, dict) or tool.get("type") not in {"function", "custom", "namespace"}:
                raise ValueError("Only client-executed tools are allowed")
            if tool["type"] == "namespace":
                check_tools(tool.get("tools", []))

    inspect_input(data.get("input", []))
    check_tools(data.get("tools", []))
    if data.get("background") or data.get("conversation") or data.get("previous_response_id"):
        raise ValueError("Only stateless foreground inference is allowed")
    if path == "/responses":
        data["store"] = False
    else:
        # Compaction has no declared persistence control.  In particular, do
        # not forward a caller-provided ``store=true`` to an upstream service.
        data.pop("store", None)
    return json.dumps(data, separators=(",", ":")).encode()


def _responses_response_semantics(path, content_type, body):
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
    usage = response.get("usage")
    return {"outcome": outcome, "reason": reason,
            "usage": normalize_usage(usage,
                                      input_details=usage.get("input_tokens_details")
                                      if isinstance(usage, dict) else None,
                                      output_details=usage.get("output_tokens_details")
                                      if isinstance(usage, dict) else None)}


class WireAdapter(Protocol):
    """Interface implemented by one provider-wire family.

    Adapters own wire-specific request validation, HTTP authentication/header
    conventions, terminal response parsing, and usage mapping.  They must not
    start threads, persist evidence, or enforce session budgets; those remain
    the gateway's responsibilities.
    """

    id: str

    def validate_request(self, path: str, body: bytes, model: str) -> bytes: ...

    def prepare_request(self, path: str, body: bytes, model: str, credential: str) -> WireRequest: ...

    def response_semantics(self, path: str, content_type: str, body: bytes) -> dict: ...


class _ResponsesWireAdapter:
    id = "responses"

    def validate_request(self, path, body, model):
        return _validate_responses_request(path, body, model)

    def prepare_request(self, path, body, model, credential):
        return WireRequest("POST", path, {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        })

    def response_semantics(self, path, content_type, body):
        return _responses_response_semantics(path, content_type, body)


_WIRE_ADAPTERS: dict[str, WireAdapter] = {}


def register_wire_adapter(adapter: WireAdapter, *, replace=False):
    """Register a trusted wire-family adapter at the gateway seam.

    An adapter is selected only by the frozen ``wire_api`` profile field.
    Registration is process-local and intended for framework integrations and
    deterministic tests; it is not a plugin loader for task-controlled code.
    """
    name = getattr(adapter, "id", None)
    if (not isinstance(name, str) or not name or name != name.strip()
            or any(not (character.isalnum() or character in "-_.") for character in name)):
        raise ValueError("Wire adapter id must be a nonempty stable name")
    required = ("validate_request", "prepare_request", "response_semantics")
    if any(not callable(getattr(adapter, method, None)) for method in required):
        raise TypeError(f"Wire adapter {name!r} does not implement the gateway interface")
    if name in _WIRE_ADAPTERS and not replace:
        raise ValueError(f"Wire adapter already registered: {name}")
    _WIRE_ADAPTERS[name] = adapter


def unregister_wire_adapter(name):
    """Remove a process-local adapter, primarily for isolated tests."""
    if name == "responses":
        raise ValueError("The built-in responses adapter cannot be removed")
    _WIRE_ADAPTERS.pop(name, None)


def available_wire_adapters():
    """Return the registered wire-family ids in deterministic order."""
    return tuple(sorted(_WIRE_ADAPTERS))


register_wire_adapter(_ResponsesWireAdapter())


def _wire_adapter(name: str) -> WireAdapter:
    adapter = _WIRE_ADAPTERS.get(name)
    if adapter is None:
        raise ValueError(
            f"Unsupported inference wire_api: {name!r}; "
            "add a wire adapter instead of coupling a harness to the runner"
        )
    return adapter


def validate_harness_wire(harness_wire_api, gateway_wire_api):
    """Ensure an explicitly declared harness bridge uses this gateway family."""
    if harness_wire_api is not None and harness_wire_api != gateway_wire_api:
        raise ValueError("Harness wire_api differs from the inference profile")


def validate_request(path, body, model, wire_api):
    """Validate a request using the selected provider-wire adapter."""
    return _wire_adapter(wire_api).validate_request(path, body, model)


def response_semantics(path, content_type, body, wire_api):
    """Validate a response using the selected provider-wire adapter."""
    return _wire_adapter(wire_api).response_semantics(path, content_type, body)


class InferenceGateway:
    """Provider-neutral gateway backed by one registered wire adapter."""

    def __init__(self, config, *, transport=None):
        self.config = config
        self.wire_adapter = _wire_adapter(config.wire_api)
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
        self.denied_events = []
        self.limit_reached = False
        self.deadline = 0
        self._started_monotonic = None
        self._stopped_monotonic = None
        self.server = None
        self.recorder = None
        self.shutdown_incomplete = False
        self._stopped = False

    @property
    def public(self):
        return {"model": self.config.model, "base_url": self.config.base_url,
                "wire_api": self.config.wire_api,
                "socket": INFERENCE_SOCKET,
                "max_requests": self.config.max_requests,
                "request_timeout_seconds": self.config.request_timeout_seconds,
                "max_input_tokens": self.config.max_input_tokens,
                "max_output_tokens": self.config.max_output_tokens,
                "max_wall_seconds": self.config.max_wall_seconds,
                "transport": "test" if self.is_test else "https",
                "source_sha256": Asset(Path(__file__).read_bytes(), "python").sha256}

    def _https(self, path, body, timeout):
        url = urlsplit(self.config.base_url)
        request_deadline = min(self.deadline, time.monotonic() + timeout)
        prepared = self.wire_adapter.prepare_request(path, body, self.config.model, self._key)
        if not isinstance(prepared, WireRequest):
            raise TypeError("Wire adapter returned an invalid HTTP request")
        relative = urlsplit(prepared.path)
        if (prepared.method.upper() != prepared.method or not prepared.method.isalpha()
                or relative.scheme or relative.netloc or not relative.path.startswith("/")):
            raise ValueError("Wire adapter returned an unsafe HTTP request")
        headers = dict(prepared.headers)
        if (any(not isinstance(name, str) or not name or "\r" in name or "\n" in name for name in headers)
                or any(not isinstance(value, str) or "\r" in value or "\n" in value for value in headers.values())):
            raise ValueError("Wire adapter returned unsafe HTTP headers")
        connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=timeout)
        self._connection = connection
        try:
            connection.connect()
            self._socket = connection.sock
            remaining = min(self.deadline, request_deadline) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Inference deadline exceeded before sending")
            self._socket.settimeout(remaining)
            connection.request(prepared.method, url.path.rstrip("/") + prepared.path, body=body,
                               headers=headers)
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

    def _deny(self, reason):
        self.denied += 1
        event = {"reason": reason, "sequence": len(self.denied_events) + 1}
        self.denied_events.append(event)
        self._record("inference.denied", **event)

    def _token_budget_reason(self):
        totals = {}
        for field, limit in (("input_tokens", self.config.max_input_tokens),
                             ("output_tokens", self.config.max_output_tokens)):
            if limit is None:
                continue
            values = [event["usage"].get(field) if isinstance(event.get("usage"), dict) else None
                      for event in self.events]
            if values and all(type(value) is int and value >= 0 for value in values):
                totals[field] = sum(values)
                if totals[field] >= limit:
                    return f"{field[:-7]}_token_budget_exhausted"
        return None

    def request(self, path, body):
        if self._stopped:
            self._deny("session_stopped")
            return 429, "application/json", b'{"error":"Inference session stopped"}'
        if not self._lock.acquire(blocking=False):
            self._deny("concurrent_request")
            return 429, "application/json", b'{"error":"Concurrent inference is disabled"}'
        try:
            if self._stopped:
                self._deny("session_stopped")
                return 429, "application/json", b'{"error":"Inference session stopped"}'
            if len(body) > MAX_BODY:
                self._deny("request_too_large")
                return 413, "application/json", b'{"error":"Request too large"}'
            if time.monotonic() >= self.deadline:
                self.limit_reached = True
                self._deny("wall_time_budget_exhausted")
                return 429, "application/json", b'{"error":"Inference budget exhausted"}'
            if len(self.events) >= self.config.max_requests:
                self.limit_reached = True
                self._deny("request_budget_exhausted")
                return 429, "application/json", b'{"error":"Inference budget exhausted"}'
            token_reason = self._token_budget_reason()
            if token_reason:
                self.limit_reached = True
                self._deny(token_reason)
                return 429, "application/json", b'{"error":"Inference budget exhausted"}'
            try:
                payload = self.wire_adapter.validate_request(path, body, self.config.model)
            except (ValueError, TypeError, RecursionError):
                self._deny("invalid_request")
                return 400, "application/json", b'{"error":"Request violates inference profile"}'
            request_started = time.monotonic()
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
                    try:
                        semantics = self.wire_adapter.response_semantics(path, content_type, response)
                    except Exception:  # noqa: BLE001 -- keep the upstream status and hide malformed bodies
                        event["outcome"] = "protocol_or_transport_error"
                        result = status, "application/json", GENERIC_RESPONSE_ERROR
                    else:
                        event.update(semantics)
                        result = status, content_type, response
                else:
                    event["outcome"] = "http_error"
                    result = status, "application/json", GENERIC_HTTP_ERROR
                event["content_type"] = content_type
            except RecordingError:
                raise
            except Exception:  # noqa: BLE001 -- never expose transport exceptions or credential-bearing bodies
                event["cancelled"] = time.monotonic() >= self.deadline
                event["status"] = 499 if event["cancelled"] else 502
                event["outcome"] = "cancelled" if event["cancelled"] else "protocol_or_transport_error"
                result = 502, "application/json", b'{"error":"Inference transport failed"}'
            event["elapsed_seconds"] = max(0.0, time.monotonic() - request_started)
            if self._token_budget_reason():
                event["budget_exceeded"] = True
                self.limit_reached = True
            event["finished_at"] = time.time()
            self._record("inference.result", **event)
            return result
        finally:
            self._lock.release()

    def start(self, path, deadline, *, uid=None):
        self._started_monotonic = time.monotonic()
        self._stopped_monotonic = None
        self.deadline = deadline
        if self.config.max_wall_seconds is not None:
            self.deadline = min(self.deadline, self._started_monotonic + self.config.max_wall_seconds)
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
                except (OSError, ValueError, KeyError, TypeError, RecursionError):
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
        self._stopped_monotonic = time.monotonic()
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
        usage, usage_observed = {}, {}
        for field in USAGE_FIELDS:
            values = [e["usage"].get(field) if isinstance(e["usage"], dict) else None for e in self.events]
            known = sum(value is not None for value in values)
            usage_observed[field] = {"known": known, "missing": len(values) - known}
            if not values or any(value is None for value in values):
                usage[field] = None
            elif field == "cost":
                usage[field] = sum(values) if all(type(value) in {int, float} and math.isfinite(value)
                                                  and value >= 0 for value in values) else None
            else:
                usage[field] = sum(values) if all(type(value) is int and value >= 0 for value in values) else None
        # A configured profile is not evidence that a model was contacted.
        # Denied requests never enter ``events``; only a forwarded request is
        # enough to classify a run as a model/protocol run.
        run_kind = ("offline_cli_development" if not self.events else
                    "model_protocol_test" if self.is_test else "model_cli_development")
        wall_seconds = ((self._stopped_monotonic - self._started_monotonic)
                        if self._started_monotonic is not None and self._stopped_monotonic is not None
                        else sum(event.get("elapsed_seconds", 0.0) for event in self.events))
        outcomes = [event.get("outcome") for event in self.events]
        counts = {
            "forwarded": len(self.events), "denied": self.denied,
            "failed": sum(outcome in FAILED_OUTCOMES for outcome in outcomes),
            "truncated": sum(outcome == "budget_truncated" for outcome in outcomes),
            "content_filtered": sum(outcome == "content_filtered" for outcome in outcomes),
            "cancelled": sum(outcome == "cancelled" for outcome in outcomes),
        }
        denied_reasons = {}
        for event in self.denied_events:
            denied_reasons[event["reason"]] = denied_reasons.get(event["reason"], 0) + 1
        return {**self.public, "run_kind": run_kind, "requests": copy.deepcopy(self.events), "usage": usage,
                "usage_observed": usage_observed, "wall_seconds": wall_seconds,
                "request_counts": counts, "denied_requests": self.denied,
                "denied_reasons": denied_reasons, "denied": copy.deepcopy(self.denied_events),
                "budget": {"max_requests": self.config.max_requests,
                           "max_input_tokens": self.config.max_input_tokens,
                           "max_output_tokens": self.config.max_output_tokens,
                           "max_wall_seconds": self.config.max_wall_seconds},
                "limit_reached": self.limit_reached,
                "shutdown_incomplete": self.shutdown_incomplete,
                "infrastructure_error": self.shutdown_incomplete or any(e["outcome"] not in {"completed", "budget_truncated",
                                                                  "content_filtered", "cancelled"}
                                            for e in self.events)}


# Compatibility name for callers that used the original implementation name.
# It does not select a different implementation; profiles still choose the
# registered wire family through ``wire_api``.
ResponsesGateway = InferenceGateway
