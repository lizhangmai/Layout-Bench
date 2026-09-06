"""Harness profiles and the common Layout-Bench session protocol.

The benchmark owns the session protocol, not an Agent framework's internal
conversation.  A harness is therefore an opaque executable by default.  A
built-in profile may prepare a command and reviewed files, but it must still
produce the same session interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .evaluation import identifier
from .files import Asset, keys, text

SESSION_PROTOCOL = "layout-session.v1"
DEFAULT_HARNESS_ID = "external-cli"
DEFAULT_HARNESS_VERSION = "1"
HARNESS_MODES = frozenset({"opaque", "managed", "native"})


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


@dataclass(frozen=True)
class PreparedHarness:
    """A harness profile's contribution to a frozen run configuration."""

    spec: HarnessSpec
    command: tuple[str, ...] | None = None
    files: dict[str, Asset] | None = None


class HarnessAdapter(Protocol):
    """Prepare one named harness without changing the session runner."""

    id: str

    def prepare(self, raw: dict[str, Any], root: Path) -> PreparedHarness: ...


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


class _ExternalCliAdapter:
    id = DEFAULT_HARNESS_ID

    def prepare(self, raw: dict[str, Any], root: Path) -> PreparedHarness:
        return PreparedHarness(
            spec=_spec(raw, defaults=HarnessSpec()),
        )


class _CodexAdapter:
    """Optional built-in profile; the runner only sees its generic output."""

    id = "codex"

    def prepare(self, raw: dict[str, Any], root: Path) -> PreparedHarness:
        defaults = HarnessSpec(
            id=self.id,
            mode="native",
            capabilities=("tools", "model_gateway"),
            wire_api="responses",
        )
        return PreparedHarness(
            spec=_spec(raw, defaults=defaults),
            command=("python", "/agent/codex_cli.py"),
            files={
                "codex_cli.py": Asset(
                    (Path(__file__).with_name("codex_cli.py")).read_bytes(),
                    "python",
                )
            },
        )


_ADAPTERS: dict[str, HarnessAdapter] = {
    DEFAULT_HARNESS_ID: _ExternalCliAdapter(),
    "codex": _CodexAdapter(),
}


def prepare_harness(data: dict[str, Any], root: Path) -> PreparedHarness:
    """Resolve the generic harness section and optional legacy spelling.

    ``adapter = "codex"`` remains accepted as a migration path for existing
    preview configurations.  New configurations should use ``[harness]``;
    the core parser never branches on a provider-specific adapter name.
    """

    if "harness" in data and "adapter" in data:
        raise ValueError("Use [harness] or legacy adapter, not both")
    if "harness" in data:
        raw = data["harness"]
        if not isinstance(raw, dict):
            raise TypeError("harness must be a table")
    elif "adapter" in data:
        if data["adapter"] != "codex":
            raise ValueError("Legacy adapter only supports codex; use [harness] for a custom profile")
        raw = {"id": data["adapter"]}
    else:
        raw = {"id": DEFAULT_HARNESS_ID}

    harness_id = identifier(raw.get("id", DEFAULT_HARNESS_ID))
    adapter = _ADAPTERS.get(harness_id)
    if adapter is None:
        adapter = _ADAPTERS[DEFAULT_HARNESS_ID]
    prepared = adapter.prepare(raw, root)
    if prepared.spec.id == "codex" and "command" in data:
        raise ValueError("The codex harness profile supplies its own command")
    if prepared.spec.id != "codex" and prepared.command is not None:
        raise ValueError("Only a built-in harness profile may supply a command")
    return prepared
