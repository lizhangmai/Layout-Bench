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


def _validate_case(data: dict) -> None:
    """Validate the inventory half of a unified circuit case."""
    _keys(data, {"schema_version", "kind", "id", "title", "status", "origin", "sources"},
          {"role", "task", "source_export", "assets", "qualification"}, "case")
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise ValueError("Unsupported case schema_version")
    if data["kind"] != "layout_case":
        raise ValueError("Only layout_case cases are supported")
    for field in ("id", "title", "status"):
        _text(data[field], f"case.{field}")
    if data["status"] not in {"candidate", "qualified", "source-only", "supporting-source"}:
        raise ValueError("Case status is not recognized")
    origin = data["origin"]
    _keys(origin, {"checkout", "commit", "license"}, set(), "case.origin")
    for field in ("checkout", "commit", "license"):
        _text(origin[field], f"case.origin.{field}")
    sources = data["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("Case needs at least one source")
    seen = set()
    for source in sources:
        _keys(source, {"id", "path", "role", "format", "sha256", "bytes"}, set(), "case.sources")
        source_id = _text(source["id"], "case.sources.id")
        if source_id in seen:
            raise ValueError(f"Duplicate case source: {source_id}")
        seen.add(source_id)
        _relative(source["path"], "case.sources.path")
        _text(source["role"], "case.sources.role")
        _text(source["format"], "case.sources.format")
        if not isinstance(source["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            raise ValueError("case.sources.sha256 must be a lowercase SHA-256")
        if type(source["bytes"]) is not int or source["bytes"] <= 0:
            raise ValueError("case.sources.bytes must be a positive integer")
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        raise TypeError("case.assets must be an array")
    for asset in assets:
        _keys(asset, {"path", "role", "visibility", "format", "sha256", "bytes"}, set(), "case.assets")
        _relative(asset["path"], "case.assets.path")
        _text(asset["role"], "case.assets.role")
        if asset["visibility"] not in {"agent", "evaluator", "maintainer"}:
            raise ValueError("case.assets.visibility is not recognized")
        _text(asset["format"], "case.assets.format")
        if not isinstance(asset["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
            raise ValueError("case.assets.sha256 must be a lowercase SHA-256")
        if type(asset["bytes"]) is not int or asset["bytes"] <= 0:
            raise ValueError("case.assets.bytes must be a positive integer")
    qualification = data.get("qualification")
    if qualification is not None:
        _keys(qualification, {"evidence", "reference"}, set(), "case.qualification")
        _relative(qualification["evidence"], "case.qualification.evidence")
        _relative(qualification["reference"], "case.qualification.reference")


def _load_task_data(data: dict, config: Path, raw: bytes, *, label: str) -> Task:
    """Load the executable task section from either schema."""
    config = config.absolute()
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
        _keys(entry, required, {"format", "source"}, f"inputs.{role}")
        relative = _relative(entry["path"], f"inputs.{role}.path")
        source_relative = _relative(entry.get("source", relative), f"inputs.{role}.source")
        if any(relative == p or relative.startswith(p + "/") or p.startswith(relative + "/")
               for p in seen_paths):
            raise ValueError(f"Overlapping task input paths: {relative}")
        seen_paths.add(relative)
        digest = entry["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"inputs.{role}.sha256 must be a lowercase SHA-256")
        content = _read_file(config.parent, source_relative)
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
        _keys(origin, {"path", "sha256"}, {"source"}, "provenance")
        path = _relative(origin["path"], "provenance.path")
        if path in seen_paths:
            raise ValueError("Preparation provenance must not be an Agent input")
        source = _relative(origin.get("source", path), "provenance.source")
        if hashlib.sha256(_read_file(config.parent, source)).hexdigest() != origin["sha256"]:
            raise ValueError("Preparation provenance checksum mismatch")
    return Task(
        data["id"], data["title"], data["family"], data["status"], data["environment"], subcircuit,
        tuple(inputs), LayoutOutput(output_path, top_cell, output["max_bytes"]),
        hashlib.sha256(raw).hexdigest(), evaluation,
    )


def load_task(config: Path) -> Task:
    """Read a standalone task or the executable section of a circuit case."""
    config = config.absolute()
    if config.resolve(strict=True) != config or not config.is_file():
        raise ValueError("Task configuration must be a regular, non-symlink file")
    raw = config.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    if data.get("kind") != "layout_case":
        return _load_task_data(data, config, raw, label="task")
    _validate_case(data)
    task_data = data.get("task")
    if task_data is None:
        raise ValueError(f"Case {data['id']} does not declare an executable task")
    if not isinstance(task_data, dict):
        raise TypeError("case.task must be a table")
    task_data = dict(task_data)
    task_data.update({"schema_version": 1, "id": data["id"], "title": data["title"],
                      "status": data["status"]})
    return _load_task_data(task_data, config, raw, label="case.task")
