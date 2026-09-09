"""Bind trusted evaluator tools from a standalone config or a circuit case."""

import tomllib
from collections.abc import Callable
from pathlib import Path

from .evaluate import Backend
from .files import keys, read_file
from .geometry import KLayoutGeometryDocker
from .klayout import KLayoutDocker
from .magic import MagicCapacitanceDocker, MagicRCDocker
from .ngspice import NgspiceDocker


def load_toolchain(config: Path, *, factories: dict[str, Callable[..., Backend]] | None = None) -> dict[str, Backend]:
    """Bind operations using trusted factories; never import code named by a task.

    Python callers can supply additional factories without changing evaluation.
    Read either a schema-1 toolchain or the [toolchain] table of a schema-2
    layout_case. Backend settings retain their existing path semantics.
    Toolchain configuration is never a solver input.
    """
    config = config.absolute()
    data = tomllib.loads(read_file(config.parent, config.name).decode("utf-8"))
    if "kind" in data:
        if data["kind"] != "layout_case" or type(data.get("schema_version")) is not int or data["schema_version"] != 2:
            raise ValueError("Embedded toolchains require a schema-2 layout_case; supply --toolchain")
        if "toolchain" not in data:
            raise ValueError("Case does not declare a toolchain; supply --toolchain")
        data = data["toolchain"]
    keys(data, {"schema_version", "backends", "bindings"}, set(), "toolchain")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported toolchain schema_version")
    if not isinstance(data["backends"], dict) or not isinstance(data["bindings"], dict):
        raise TypeError("Toolchain backends and bindings must be tables")
    factories = {"ngspice-docker": NgspiceDocker,
                 "magic-capacitance-docker": MagicCapacitanceDocker,
                 "magic-rc-docker": MagicRCDocker,
                 "klayout-docker": KLayoutDocker,
                 "klayout-geometry-docker": KLayoutGeometryDocker} if factories is None else factories
    for name, config_data in data["backends"].items():
        keys(config_data, {"type", "settings"}, set(), f"backend {name}")
        if config_data["type"] not in factories or not isinstance(config_data["settings"], dict):
            raise ValueError(f"Unknown or invalid backend: {name}")
    if not all(isinstance(value, str) and value in data["backends"] for value in data["bindings"].values()):
        raise ValueError("Toolchain binding references an unknown backend")
    instances = {name: factories[entry["type"]](**entry["settings"])
                 for name, entry in data["backends"].items() if name in data["bindings"].values()}
    return {operation: instances[name] for operation, name in data["bindings"].items()}
