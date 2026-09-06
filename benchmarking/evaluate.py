"""Execute a frozen evaluation plan with caller-supplied tool backends.

This module owns dependency handling, per-observation requirements and report
semantics. Backends own EDA execution and interpretation, including isolation.
The caller owns authorization and task/toolchain qualification.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .evaluation import EvaluationPlan, Job, number
from .files import Asset


@dataclass(frozen=True)
class Measurement:
    value: float
    unit: str


@dataclass
class JobResult:
    status: str  # passed, failed (completed check), or error (no valid result)
    reason: str = ""
    measurements: dict[str, Measurement] = field(default_factory=dict)
    outputs: dict[str, Asset] = field(default_factory=dict)
    evidence: dict[str, Asset] = field(default_factory=dict)


class Backend(Protocol):
    """A trusted tool adapter. It must not read the solver's mutable workspace.

    run receives only immutable declared inputs and fresh parameters. Return
    failed only for a completed check rejecting the artifact; tool failures and
    unsupported settings are errors. Evidence is returned as bytes for archival.
    A backend may use a container, subprocess, remote worker or native library.
    """

    @property
    def identity(self) -> dict: ...

    def run(self, job: Job, inputs: dict[str, Asset]) -> JobResult: ...


def _validate_result(job: Job, result: JobResult) -> None:
    if not isinstance(result, JobResult):
        raise TypeError("Backend must return JobResult")
    if result.status not in {"passed", "failed", "error"}:
        raise ValueError("Unknown backend status")
    if result.status == "failed" and job.stage != "check":
        raise ValueError("Only a completed check may return failed")
    if result.status != "passed" and not result.reason:
        raise ValueError("A rejected check or tool error needs a reason")
    for measurement in result.measurements.values():
        number(measurement.value)
        if not isinstance(measurement.unit, str) or not measurement.unit:
            raise ValueError("Measurements require explicit units")
    if result.status == "passed":
        expected = dict(job.outputs)
        if result.outputs.keys() != expected.keys():
            raise ValueError("Backend outputs differ from the declared outputs")
        for name, output in result.outputs.items():
            if output.format != expected[name] or not output.content:
                raise ValueError(f"Empty or incorrectly formatted output: {name}")
    elif result.measurements or result.outputs:
        raise ValueError("Unsuccessful jobs cannot publish measurements or downstream outputs")
    if not result.evidence:
        raise ValueError("Backend must return diagnostic evidence")
    for asset in (*result.outputs.values(), *result.evidence.values()):
        if not isinstance(asset, Asset) or not isinstance(asset.content, bytes) or not asset.format:
            raise ValueError("Backend artifacts must be typed byte snapshots")


def run_evaluation(plan: EvaluationPlan, inputs: dict[str, Asset],
                   backends: dict[str, Backend], destination: Path, *,
                   task_sha256: str | None = None) -> dict:
    """Execute all independent jobs; block dependents of failed/error jobs.

    inputs is keyed by candidate, task or input:<role>. Backends are keyed by logical
    operation, selected by the trusted caller, never imported from task TOML.
    This command produces local evidence, not a signed official benchmark score.
    """
    missing = plan.external_inputs() - inputs.keys()
    if missing:
        raise ValueError(f"Missing evaluation inputs: {sorted(missing)}")
    operations = {job.operation for job in plan.jobs}
    if not operations <= backends.keys():
        raise ValueError(f"Missing backend bindings: {sorted(operations - backends.keys())}")
    identities = {op: backends[op].identity for op in sorted(operations)}
    # Validate JSON compatibility before creating an output directory.
    identities = json.loads(json.dumps(identities, allow_nan=False))
    assets = {ref: inputs[ref] for ref in plan.external_inputs()}
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Evaluation destination already exists: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    artifact_root = destination / "artifacts"
    artifact_root.mkdir(mode=0o700)
    artifact_root.chmod(0o700)

    def archive(asset: Asset) -> dict:
        path = artifact_root / asset.sha256
        if not path.exists():
            path.write_bytes(asset.content)
            path.chmod(0o400)
        return {**asset.identity(), "path": f"artifacts/{asset.sha256}"}

    report = {
        "schema_version": 1, "mode": plan.mode, "task_sha256": task_sha256,
        "engine_sha256": {name: Asset(Path(__file__).with_name(name).read_bytes(), "python").sha256
                          for name in ("evaluate.py", "evaluation.py", "files.py")},
        "plan": archive(Asset(plan.raw, "toml")), "backends": identities,
        "inputs": {ref: archive(asset) for ref, asset in sorted(assets.items())},
        "jobs": {}, "metrics": {},
    }
    results: dict[str, JobResult] = {}
    for job in plan.jobs:
        blocked = [dep for dep in job.requires if results[dep].status != "passed"]
        if blocked:
            result = JobResult("blocked", f"Prerequisites did not pass: {', '.join(blocked)}")
        else:
            try:
                result = backends[job.operation].run(job, {k: assets[v] for k, v in job.inputs})
                _validate_result(job, result)
            except Exception as error:  # noqa: BLE001 -- preserve evidence when an adapter itself is broken
                # Persist the distinction between a failing circuit and a broken
                # adapter. Unrelated jobs still produce useful diagnostics.
                result = JobResult("error", f"{type(error).__name__}: {error}")
        results[job.id] = result
        entry = {
            "status": result.status, "reason": result.reason,
            "operation": job.operation, "stage": job.stage, "gate": job.gate,
            "requires": list(job.requires), "parameters": job.parameters,
            "inputs": {name: assets[ref].identity() for name, ref in job.inputs if ref in assets},
            "outputs": {name: archive(asset) for name, asset in result.outputs.items()},
            "evidence": {name: archive(asset) for name, asset in result.evidence.items()},
            "measurements": {name: {"value": number(m.value), "unit": m.unit}
                             for name, m in result.measurements.items()},
        }
        report["jobs"][job.id] = entry
        for name, asset in result.outputs.items():
            assets[f"job:{job.id}:{name}"] = asset

    for metric in plan.metrics:
        observations = {}
        for ref in metric.observations:
            job_id, name = ref.split(":")
            result = results[job_id]
            measurement = result.measurements.get(name)
            if result.status != "passed":
                observations[ref] = {"status": "blocked", "reason": result.reason}
            elif measurement is None:
                observations[ref] = {"status": "error", "reason": "Declared measurement missing"}
            elif measurement.unit != metric.unit:
                observations[ref] = {"status": "error", "reason": f"Expected unit {metric.unit}, got {measurement.unit}"}
            else:
                value = number(measurement.value)
                passed = ((metric.lower is None or value >= metric.lower)
                          and (metric.upper is None or value <= metric.upper))
                observations[ref] = {"status": "passed" if passed else "failed", "value": value}
        valid = all("value" in obs for obs in observations.values())
        status = ("error" if any(o["status"] == "error" for o in observations.values())
                  else "blocked" if not valid
                  else "failed" if any(o["status"] == "failed" for o in observations.values())
                  else "passed")
        # Bounds apply to EACH observation, independent of the displayed summary.
        value = (min if metric.aggregation == "min" else max)(
            o["value"] for o in observations.values()) if valid else None
        report["metrics"][metric.id] = {
            "category": metric.category, "unit": metric.unit, "direction": metric.direction,
            "lower": metric.lower, "upper": metric.upper, "aggregation": metric.aggregation,
            "value": value, "status": status, "observations": observations,
        }

    gate_status = [results[j.id].status for j in plan.jobs if j.gate in {"artifact", "drc", "lvs"}]
    physical_valid = (None if plan.mode == "characterization"
                      else False if "failed" in gate_status
                      else True if all(s == "passed" for s in gate_status) else None)
    requirements = [report["metrics"][m.id]["status"] for m in plan.metrics if m.is_requirement]
    specs_pass = (None if not requirements
                  else False if "failed" in requirements
                  else True if all(s == "passed" for s in requirements) else None)
    statuses = [r.status for r in results.values()] + [m["status"] for m in report["metrics"].values()]
    # A completed check or metric rejection is a conclusive negative result,
    # even if an unrelated adapter also failed.  Keep an evaluator error as
    # the outcome only when no part of the candidate is known to be invalid;
    # otherwise callers must not drop the known-bad candidate from statistics.
    outcome = ("failed" if "failed" in statuses else "error" if "error" in statuses
               else "incomplete" if "blocked" in statuses else "passed")
    task_success = None
    if plan.mode == "post_layout":
        task_success = (False if physical_valid is False or outcome == "failed"
                        else True if outcome == "passed" else None)
    report.update(outcome=outcome, physical_valid=physical_valid, specs_pass=specs_pass,
                  task_success=task_success,
                  quality_eligible=task_success is True)
    report_path = destination / "report.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    report_path.chmod(0o600)
    return report
