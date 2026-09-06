"""Load a task configuration and materialize only its verified input files.

Loading checks configuration and content integrity. It does not qualify the
circuit/evaluator or grant access to a hidden task; those are maintainer duties.
"""

import hashlib
import json
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .evaluation import EvaluationPlan, identifier, parse_evaluation
from .files import Asset
from .files import keys as _keys
from .files import read_file as _read_file
from .files import relative as _relative
from .files import text as _text


@dataclass(frozen=True)
class InputFile:
    role: str
    path: str
    sha256: str
    content: bytes
    format: str = "text"


@dataclass(frozen=True)
class LayoutOutput:
    path: str
    top_cell: str
    max_bytes: int


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    family: str
    status: str
    environment: str
    netlist_subcircuit: str
    inputs: tuple[InputFile, ...]
    output: LayoutOutput
    digest: str
    evaluation: EvaluationPlan | None = None

    def evaluation_inputs(self) -> dict[str, Asset]:
        return {
            "task": Asset(json.dumps(self.description(), sort_keys=True).encode(), "json"),
            **{f"input:{item.role}": Asset(item.content, item.format) for item in self.inputs},
        }

    def description(self) -> dict:
        """Return execution paths without exposing preparation/source metadata."""
        return {
            "id": self.id,
            "title": self.title,
            "family": self.family,
            "status": self.status,
            "task_sha256": self.digest,
            "environment": self.environment,
            "netlist_subcircuit": self.netlist_subcircuit,
            "input_root": "/task",
            "inputs": {item.role: f"/task/{item.path}" for item in self.inputs},
            "evaluation": self.evaluation.description() if self.evaluation else None,
            "output": {
                "path": f"/workspace/{self.output.path}",
                "format": "gds",
                "top_cell": self.output.top_cell,
                "max_bytes": self.output.max_bytes,
            },
        }

    def materialize(self, destination: Path) -> None:
        """Publish a fresh input directory from the bytes already validated.

        The caller mounts this directory at /task, read-only. No source checkout,
        task metadata, reference solution or other neighboring file is copied.
        """
        destination = destination.absolute()
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            stage = Path(temporary) / "inputs"
            stage.mkdir()
            for item in self.inputs:
                target = stage / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.content)
                target.chmod(0o444)
            stage.rename(destination)


def load_task(config: Path) -> Task:
    """Read task.toml, reject unsupported fields and verify each declared input."""
    config = config.absolute()
    if config.resolve(strict=True) != config or not config.is_file():
        raise ValueError("Task configuration must be a regular, non-symlink file")
    raw = config.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    _keys(data, {"schema_version", "id", "title", "kind", "family", "status",
                 "environment", "inputs", "output"}, {"provenance"}, "task")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported task schema_version")
    if data["kind"] != "netlist_to_gds":
        raise ValueError("Only netlist_to_gds tasks are supported")
    if data["status"] not in {"candidate", "qualified"}:
        raise ValueError("Task status must be candidate or qualified")
    for field in ("id", "title", "family", "environment"):
        _text(data[field], field)
    if not isinstance(data["inputs"], dict):
        raise TypeError("inputs must be a table")
    _keys(data["inputs"], {"netlist", "constraints"}, set(data["inputs"]), "inputs")
    inputs = []
    seen_paths: set[str] = set()
    for role, entry in data["inputs"].items():
        identifier(role)
        required = {"path", "sha256", "subcircuit"} if role == "netlist" else {"path", "sha256"}
        _keys(entry, required, {"format"}, f"inputs.{role}")
        relative = _relative(entry["path"], f"inputs.{role}.path")
        if any(relative == p or relative.startswith(p + "/") or p.startswith(relative + "/")
               for p in seen_paths):
            raise ValueError(f"Overlapping task input paths: {relative}")
        seen_paths.add(relative)
        digest = entry["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"inputs.{role}.sha256 must be a lowercase SHA-256")
        content = _read_file(config.parent, relative)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"Task input checksum mismatch: {relative}")
        inputs.append(InputFile(role, relative, digest, content,
                                _text(entry.get("format", "text"), "input format")))
    evaluation = next((parse_evaluation(item.content) for item in inputs if item.role == "evaluation"), None)
    if evaluation:
        available = {"candidate", "task"} | {f"input:{item.role}" for item in inputs}
        if not evaluation.external_inputs() <= available:
            raise ValueError("Evaluation references an undeclared task input")
    output = data["output"]
    subcircuit = _text(data["inputs"]["netlist"]["subcircuit"], "inputs.netlist.subcircuit")
    _keys(output, {"path", "format", "top_cell", "max_bytes"}, set(), "output")
    if output["format"] != "gds":
        raise ValueError("Only GDS output is supported")
    output_path = _relative(output["path"], "output.path")
    top_cell = _text(output["top_cell"], "output.top_cell")
    if type(output["max_bytes"]) is not int or output["max_bytes"] <= 0:
        raise ValueError("output.max_bytes must be a positive integer")
    if "provenance" in data:
        origin = data["provenance"]
        _keys(origin, {"path", "sha256"}, set(), "provenance")
        path = _relative(origin["path"], "provenance.path")
        if path in seen_paths:
            raise ValueError("Preparation provenance must not be an Agent input")
        if hashlib.sha256(_read_file(config.parent, path)).hexdigest() != origin["sha256"]:
            raise ValueError("Preparation provenance checksum mismatch")
    return Task(
        data["id"], data["title"], data["family"], data["status"], data["environment"], subcircuit,
        tuple(inputs), LayoutOutput(output_path, top_cell, output["max_bytes"]),
        hashlib.sha256(raw).hexdigest(), evaluation,
    )
