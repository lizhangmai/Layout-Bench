"""Generic harness metadata for the common Layout-Bench session protocol.

The benchmark owns the session protocol, not an Agent framework's internal
conversation. A harness is therefore an opaque executable by default and
supplies its own command and reviewed files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evaluation import identifier
from .files import keys, text

SESSION_PROTOCOL = "layout-session.v1"
DEFAULT_HARNESS_ID = "external-cli"
DEFAULT_HARNESS_VERSION = "1"
HARNESS_MODES = frozenset({"opaque", "managed", "native"})
PROCESS_FEEDBACK_CAPABILITY = "process-feedback.v1"


@dataclass(frozen=True)
class HarnessSpec:
    """The observable identity and semantics of one Agent harness."""

    id: str = DEFAULT_HARNESS_ID
    version: str = DEFAULT_HARNESS_VERSION
    protocol: str = SESSION_PROTOCOL
    mode: str = "opaque"
    capabilities: tuple[str, ...] = ()
    wire_api: str | None = None

    def identity(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "protocol": self.protocol,
            "mode": self.mode,
            "capabilities": list(self.capabilities),
            "wire_api": self.wire_api,
        }


def _spec(raw: dict[str, Any], *, defaults: HarnessSpec) -> HarnessSpec:
    keys(
        raw,
        set(),
        {"id", "version", "protocol", "mode", "capabilities", "wire_api"},
        "harness",
    )
    harness_id = identifier(raw.get("id", defaults.id))
    version = text(raw.get("version", defaults.version), "harness.version")
    protocol = text(raw.get("protocol", defaults.protocol), "harness.protocol")
    if protocol != SESSION_PROTOCOL:
        raise ValueError(f"Unsupported harness.protocol={protocol!r}; expected {SESSION_PROTOCOL!r}")
    mode = text(raw.get("mode", defaults.mode), "harness.mode")
    if mode not in HARNESS_MODES:
        raise ValueError(
            f"Unsupported harness.mode={mode!r}; expected one of "
            f"{', '.join(sorted(HARNESS_MODES))}"
        )
    capabilities = raw.get("capabilities", defaults.capabilities)
    if not isinstance(capabilities, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in capabilities
    ):
        raise TypeError("harness.capabilities must be a list of nonempty strings")
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("harness.capabilities must not contain duplicates")
    wire_api = raw.get("wire_api", defaults.wire_api)
    if wire_api is not None:
        wire_api = text(wire_api, "harness.wire_api")
    return HarnessSpec(
        id=harness_id,
        version=version,
        protocol=protocol,
        mode=mode,
        capabilities=tuple(capabilities),
        wire_api=wire_api,
    )


def prepare_harness(data: dict[str, Any]) -> HarnessSpec:
    """Validate generic harness metadata without selecting a provider runtime."""

    raw = data.get("harness", {})
    if not isinstance(raw, dict):
        raise TypeError("harness must be a table")
    return _spec(raw, defaults=HarnessSpec())
