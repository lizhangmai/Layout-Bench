"""Tool-independent evaluation plans and per-task metric definitions.

Operation names are resolved by the caller's backend bindings. No executable,
PDK, circuit family, waveform expression or simulator syntax lives here.
"""

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass

from .files import keys, text


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def number(value: object) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("Expected a finite numeric value")
    return float(value)


@dataclass(frozen=True)
class Job:
    id: str
    stage: str
    operation: str
    inputs: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, str], ...]
    requires: tuple[str, ...]
    gate: str | None
    parameters_json: str

    @property
    def parameters(self) -> dict:
        # Each backend receives its own copy, keeping the frozen plan immutable.
        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class Metric:
    id: str
    category: str
    observations: tuple[str, ...]
    unit: str
    direction: str
    aggregation: str
    lower: float | None
    upper: float | None

    @property
    def is_requirement(self) -> bool:
        return self.lower is not None or self.upper is not None


@dataclass(frozen=True)
class EvaluationPlan:
    mode: str
    jobs: tuple[Job, ...]
    metrics: tuple[Metric, ...]
    raw: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def description(self) -> dict:
        return tomllib.loads(self.raw.decode("utf-8"))

    def external_inputs(self) -> frozenset[str]:
        return frozenset(ref for job in self.jobs for _, ref in job.inputs
                         if ref in {"candidate", "task"} or ref.startswith("input:"))


def parse_evaluation(raw: bytes) -> EvaluationPlan:
    """Validate a declarative plan; return jobs in dependency order.

    Inputs use candidate, task, input:<role>, or job:<id>:<output>. Metric observations
    use <job>:<measurement>. Separate jobs express corners, loads and seeds;
    metrics retain all observations and check bounds on every one of them.
    """
    data = tomllib.loads(raw.decode("utf-8"))
    keys(data, {"schema_version", "mode", "jobs", "metrics"}, set(), "evaluation")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported evaluation schema_version")
    if data["mode"] not in {"physical", "post_layout", "characterization"}:
        raise ValueError("Unknown evaluation mode")
    if not isinstance(data["jobs"], list) or not data["jobs"]:
        raise ValueError("Evaluation needs a nonempty jobs list")
    jobs = {}
    for entry in data["jobs"]:
        keys(entry, {"id", "stage", "operation", "inputs"},
             {"outputs", "requires", "gate", "parameters"}, "job")
        name = identifier(entry["id"])
        if name in jobs:
            raise ValueError(f"Duplicate job: {name}")
        if entry["stage"] not in {"check", "extract", "simulate", "measure"}:
            raise ValueError(f"Unknown stage in {name}")
        operation = text(entry["operation"], "operation")
        gate = entry.get("gate")
        if gate is not None and (gate not in {"artifact", "drc", "lvs", "constraint"}
                                 or entry["stage"] != "check"):
            raise ValueError(f"Invalid gate in {name}")
        if not isinstance(entry["inputs"], dict) or not entry["inputs"]:
            raise ValueError(f"Job {name} needs named inputs")
        inputs = tuple((identifier(k), text(v, "input reference"))
                       for k, v in entry["inputs"].items())
        outputs = entry.get("outputs", {})
        if not isinstance(outputs, dict):
            raise TypeError("Job outputs must be a table")
        outputs = tuple((identifier(k), text(v, "output format")) for k, v in outputs.items())
        requires = entry.get("requires", [])
        if not isinstance(requires, list) or len(set(requires)) != len(requires):
            raise ValueError("Job requires must be a list of unique job ids")
        requires = tuple(identifier(x) for x in requires)
        parameters = entry.get("parameters", {})
        if not isinstance(parameters, dict):
            raise TypeError("Job parameters must be a table")
        jobs[name] = Job(name, entry["stage"], operation, inputs, outputs, requires, gate,
                         json.dumps(parameters, allow_nan=False, sort_keys=True))

    # Data dependencies also impose ordering; explicit requires is useful for
    # checks that produce evidence but no downstream circuit artifact.
    ordered = []
    pending = dict(jobs)
    ancestors: dict[str, set[str]] = {}
    data_ancestors: dict[str, set[str]] = {}
    dependencies = {}
    data_dependencies = {}
    for job in jobs.values():
        deps = set(job.requires)
        producers = set()
        for _, ref in job.inputs:
            parts = ref.split(":")
            if ref in {"candidate", "task"}:
                continue
            if len(parts) == 2 and parts[0] == "input":
                identifier(parts[1])
                continue
            if len(parts) != 3 or parts[0] != "job" or parts[1] not in jobs:
                raise ValueError(f"Unknown input reference: {ref}")
            if parts[2] not in dict(jobs[parts[1]].outputs):
                raise ValueError(f"Unknown job output: {ref}")
            producers.add(parts[1])
        deps |= producers
        if not deps <= jobs.keys():
            raise ValueError(f"Unknown job dependency in {job.id}")
        dependencies[job.id], data_dependencies[job.id] = deps, producers
    while pending:
        ready = [job for job in pending.values() if dependencies[job.id] <= ancestors.keys()]
        if not ready:
            raise ValueError("Evaluation dependency cycle")
        for job in ready:
            deps, producers = dependencies[job.id], data_dependencies[job.id]
            ancestors[job.id] = deps | set().union(*(ancestors[x] for x in deps))
            data_ancestors[job.id] = producers | set().union(*(data_ancestors[x] for x in producers))
            ordered.append(Job(job.id, job.stage, job.operation, job.inputs, job.outputs,
                               tuple(sorted(deps)), job.gate, job.parameters_json))
            del pending[job.id]

    metrics = []
    seen = set()
    if not isinstance(data["metrics"], list):
        raise TypeError("Metrics must be a list")
    for entry in data["metrics"]:
        keys(entry, {"id", "category", "observations", "unit", "direction", "aggregation"},
             {"lower", "upper"}, "metric")
        name = identifier(entry["id"])
        if name in seen:
            raise ValueError(f"Duplicate metric: {name}")
        seen.add(name)
        if entry["category"] not in {"physical", "performance"}:
            raise ValueError(f"Unknown metric category: {name}")
        if entry["direction"] not in {"minimize", "maximize", "target"}:
            raise ValueError(f"Unknown metric direction: {name}")
        if entry["aggregation"] not in {"min", "max"}:
            raise ValueError("Metric aggregation must be min or max")
        refs = entry["observations"]
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs):
            raise ValueError(f"Metric {name} needs unique observations")
        for ref in refs:
            parts = text(ref, "observation").split(":")
            if len(parts) != 2 or parts[0] not in jobs:
                raise ValueError(f"Unknown observation: {ref}")
            identifier(parts[1])
            if (jobs[parts[0]].stage not in {"simulate", "measure"}
                    and not (jobs[parts[0]].stage == "check" and entry["category"] == "physical")):
                raise ValueError(f"Observation is not produced by a measurement stage: {ref}")
        lower = number(entry["lower"]) if "lower" in entry else None
        upper = number(entry["upper"]) if "upper" in entry else None
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"Inverted bounds: {name}")
        if entry["direction"] == "target" and (lower is None or upper is None):
            raise ValueError("Target metrics require lower and upper bounds")
        metrics.append(Metric(name, entry["category"], tuple(refs), text(entry["unit"], "unit"),
                              entry["direction"], entry["aggregation"], lower, upper))

    if data["mode"] != "characterization":
        for gate in ("artifact", "drc", "lvs"):
            matches = [j for j in ordered if j.gate == gate]
            if len(matches) != 1 or "candidate" not in dict(matches[0].inputs).values():
                raise ValueError(f"Layout evaluation needs one {gate} gate on the candidate")
    if data["mode"] == "post_layout":
        gates = {j.id for j in ordered if j.gate in {"artifact", "drc", "lvs"}}
        for job in ordered:
            if job.stage == "extract" and not gates <= ancestors[job.id]:
                raise ValueError(f"Extraction must depend on physical validity gates: {job.id}")
        performance = [m for m in metrics if m.category == "performance"]
        if not any(m.is_requirement for m in performance):
            raise ValueError("Post-layout evaluation needs a performance requirement")
        for metric in performance:
            for ref in metric.observations:
                job_id = ref.split(":")[0]
                lineage = data_ancestors[job_id] | {job_id}
                simulations = [j for j in ordered if j.id in lineage and j.stage == "simulate"]
                if not simulations:
                    raise ValueError(f"Post-layout metric has no simulation: {metric.id}")
                for simulation in simulations:
                    extractors = [j for j in ordered if j.id in data_ancestors[simulation.id]
                                  and j.stage == "extract"]
                    if not any("candidate" in dict(j.inputs).values() for j in extractors):
                        raise ValueError(f"Simulation must consume candidate extraction: {simulation.id}")
    return EvaluationPlan(data["mode"], tuple(ordered), tuple(metrics), raw)
