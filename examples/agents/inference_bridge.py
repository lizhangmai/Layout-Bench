"""Small client for the Layout-Bench host inference socket.

This file is intentionally dependency-free so a harness can copy it into its
reviewed ``files`` without installing an Agent framework.  The host owns the
provider credential and HTTPS connection; a harness only sends a validated
Responses request over the per-session Unix socket.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path

MAX_BODY = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
MAX_HEADER = 1024
DEFAULT_SOCKET = "/protocol/inference.sock"
ALLOWED_PATHS = frozenset({"/responses", "/responses/compact"})


@dataclass(frozen=True)
class InferenceResponse:
    """The unmodified response frame returned by the host gateway."""

    status: int
    content_type: str
    body: bytes

    def json(self):
        """Decode a JSON response, raising ``ValueError`` on malformed data."""
        return json.loads(self.body)


def _readline(stream, limit):
    data = bytearray()
    while len(data) <= limit:
        byte = stream.recv(1)
        if not byte:
            raise ConnectionError("Inference gateway closed before the response header")
        data.extend(byte)
        if byte == b"\n":
            return bytes(data)
    raise ValueError("Inference response header exceeds the size limit")


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(min(65536, size - len(data)))
        if not chunk:
            raise ConnectionError("Inference gateway closed before the response body")
        data.extend(chunk)
    return bytes(data)


def load_profile(path="/protocol/inference.json"):
    """Load the public, non-secret gateway description mounted for a session."""
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError("Inference profile must be a JSON object")
    socket_path = value.get("socket", DEFAULT_SOCKET)
    model = value.get("model")
    if not isinstance(socket_path, str) or not socket_path.startswith("/"):
        raise ValueError("Inference profile has an invalid socket path")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Inference profile has no model")
    return value


class InferenceClient:
    """Request client for the per-session host gateway.

    Each request is one connection containing a JSON header followed by the
    exact number of body bytes.  The response uses the same framing: a JSON
    header followed by a fixed-length body.  The connection is closed after
    one response, so a retry is a new counted gateway request.
    """

    def __init__(self, profile=None, *, socket_path=None, timeout=None):
        profile = profile or load_profile()
        self.profile = profile
        self.socket_path = socket_path or profile.get("socket", DEFAULT_SOCKET)
        self.model = profile["model"]
        self.timeout = timeout

    def request(self, path, payload):
        """Send one JSON request and return an :class:`InferenceResponse`."""
        if path not in ALLOWED_PATHS:
            raise ValueError(f"Unsupported inference path: {path!r}")
        if isinstance(payload, dict):
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        elif isinstance(payload, bytes):
            body = payload
        else:
            raise TypeError("Inference payload must be a dict or bytes")
        if len(body) > MAX_BODY:
            raise ValueError("Inference request exceeds the size limit")
        header = json.dumps({"path": path, "bytes": len(body)}, separators=(",", ":")).encode() + b"\n"
        with socket.socket(socket.AF_UNIX) as connection:
            if self.timeout is not None:
                connection.settimeout(self.timeout)
            connection.connect(self.socket_path)
            connection.sendall(header + body)
            raw_header = _readline(connection, MAX_HEADER)
            try:
                response = json.loads(raw_header)
            except (TypeError, ValueError) as error:
                raise ValueError("Inference gateway returned an invalid response header") from error
            if not isinstance(response, dict):
                raise TypeError("Inference response header must be an object")
            status, content_type, size = (response.get(key) for key in ("status", "type", "bytes"))
            if (type(status) is not int or not 100 <= status <= 599
                    or not isinstance(content_type, str) or not content_type
                    or type(size) is not int or not 0 <= size <= MAX_RESPONSE):
                raise ValueError("Inference gateway returned an invalid response frame")
            return InferenceResponse(status, content_type, _read_exact(connection, size))

    def create(self, input_value, **parameters):
        """Send a Responses generation request with the fixed profile model."""
        payload = {"model": self.model, "input": input_value, **parameters}
        return self.request("/responses", payload)

    def compact(self, input_value, **parameters):
        """Send a standalone Responses compaction request."""
        payload = {"model": self.model, "input": input_value, **parameters}
        return self.request("/responses/compact", payload)
