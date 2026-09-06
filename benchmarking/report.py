"""Recompute internal development statistics from verified frozen run evidence.

This is not a public/hidden-task export policy. Outputs belong to the same
trusted operator as the complete batch directory.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist

from .admission import restore_policy
from .files import Asset, read_file
from .recorder import recover_submissions


def wilson(successes, count):
    """Two-sided 95% Wilson score interval; no fictitious zero-width extremes."""
    if type(count) is not int or type(successes) is not int or not 0 <= successes <= count:
        raise ValueError("Invalid binomial counts")
    if count == 0:
        return None
    z = NormalDist().inv_cdf(.975)
    rate = successes / count
    denominator = 1 + z*z/count
    center = (rate + z*z/(2*count)) / denominator
    half = z * math.sqrt(rate*(1-rate)/count + z*z/(4*count*count)) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def _read_json(root, reference):
    raw = read_file(root, reference["path"])
    if any(reference[key] != value for key, value in Asset(raw, "json").identity().items()):
        raise ValueError("Report artifact integrity mismatch")
    return json.loads(raw)


def _distribution(values):
    known = [v for v in values if type(v) in {int, float} and math.isfinite(v) and v >= 0]
    return {"count": len(values), "known": len(known), "missing": len(values)-len(known),
            "sum": sum(known) if known and len(known) == len(values) else None,
            "mean_known": sum(known)/len(known) if known else None,
            "min_known": min(known) if known else None, "max_known": max(known) if known else None}


def _resources(reports):
    result = {field: _distribution([(r.get("usage") or {}).get(field) if r else None for r in reports])
              for field in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens", "cost")}
    result["wall_seconds"] = _distribution([r.get("elapsed_seconds") if r else None for r in reports])
    return result


def verify_run(root, entry, manifest, execution_sha):
    report = _read_json(root, entry["report"])
    expected = {key: entry[key] for key in ("slot_id", "task_id", "configuration_id", "repeat", "attempt")}
    expected["execution_sha256"] = execution_sha
    task, agent = manifest["tasks"][entry["task_id"]], manifest["agents"][entry["configuration_id"]]
    if (report.get("schema_version") != 2 or report.get("phase") != "finished"
            or report.get("execution") != expected or report.get("task_sha256") != task["task_sha256"]
            or report.get("run_kind") != agent["run_kind"] or report.get("agent_id") != agent["agent_id"]
            or report.get("configuration", {}).get("sha256") != agent["source"]["sha256"]
            or report.get("command") != agent["command"] or report.get("public_environment") != agent["environment"]
            or report.get("environment", {}).get("image_id") != agent["image_id"]):
        raise ValueError("Run does not match its frozen execution conditions")
    for name, ref in report.get("implementation", {}).items():
        expected_source = manifest["framework"]["files"].get("benchmarking/" + name)
        if expected_source is None or ref["sha256"] != expected_source["sha256"]:
            raise ValueError("Run implementation differs from frozen framework")
    for key, value in agent["budget"].items():
        if report["environment"].get(key) != value:
            raise ValueError("Run budget differs from its frozen plan")
    for group, expected_files in (("agent_files", agent["files"]), ("resources", agent["resources"]), ("inputs", task["inputs"])):
        actual = {key: value["sha256"] for key, value in report.get(group, {}).items()}
        if actual != {key: value["sha256"] for key, value in expected_files.items()}:
            raise ValueError("Run inputs differ from its frozen plan")
    if agent["inference"]:
        if report.get("inference_profile", {}).get("sha256") != agent["inference"]["source"]["sha256"]:
            raise ValueError("Run inference profile differs from plan")
        if any(report.get("inference", {}).get(key) != value for key, value in agent["inference"]["identity"].items()):
            raise ValueError("Actual inference endpoint/model differs from plan")
    elif "inference" in report:
        raise ValueError("Offline plan unexpectedly used inference")
    run_root = (root / entry["report"]["path"]).parent
    events = report.get("events")
    if not events or any(events[key] != value for key, value in Asset(read_file(run_root, events["path"]), "jsonl").identity().items()):
        raise ValueError("Run event journal integrity mismatch")
    recovered = recover_submissions(run_root)
    if recovered["candidate"] != report.get("candidate"):
        raise ValueError("Reported candidate differs from the last durable submission")
    evaluation = None
    if report.get("evaluation"):
        ref = report["evaluation"]
        raw = read_file(run_root, ref["path"])
        if Asset(raw, "json").sha256 != ref["sha256"]:
            raise ValueError("Evaluation report integrity mismatch")
        evaluation = json.loads(raw)
        for name, digest in evaluation["engine_sha256"].items():
            if digest != manifest["framework"]["files"]["benchmarking/" + name]["sha256"]:
                raise ValueError("Evaluation implementation differs from frozen framework")
        expected_backends = {op: task["backends"][op] for op in task["operations"]}
        if (evaluation.get("task_sha256") != task["task_sha256"] or evaluation["backends"] != expected_backends
                or evaluation["inputs"]["candidate"]["sha256"] != report["candidate"]["sha256"]):
            raise ValueError("Evaluation does not match its task, candidate or toolchain")
    return report, evaluation


def summarize_batch(destination):
    root = Path(destination).absolute()
    batch = json.loads(read_file(root, "batch.json"))
    if batch.get("schema_version") != 1 or batch.get("run_kind") != "local_batch_development":
        raise ValueError("Unsupported batch report")
    if batch.get("phase") == "finished":
        events = batch["events"]
        if any(events[key] != value for key, value in Asset(read_file(root, events["path"]), "jsonl").identity().items()):
            raise ValueError("Batch event journal integrity mismatch")
    manifest = _read_json(root, batch["execution"])
    if manifest.get("schema_version") != 1 or manifest.get("run_kind") != "local_batch_development":
        raise ValueError("Unsupported execution manifest")
    if "admission" in manifest:
        policy = restore_policy(root, manifest, manifest["admission"]["policy"]["sha256"])
        reservation = batch.get("admission_reservation", {})
        if (reservation.get("policy_sha256") != policy.source.sha256
                or reservation.get("execution_sha256") != batch["execution"]["sha256"]):
            raise ValueError("Batch has no matching admission reservation")
    slots = {slot["slot_id"]: slot for slot in manifest["schedule"]}
    if len(slots) != len(manifest["schedule"]):
        raise ValueError("Duplicate scheduled slot")
    expected_points = {(task, agent, repeat) for task in manifest["tasks"] for agent in manifest["agents"]
                       for repeat in range(1, manifest["repetitions"] + 1)}
    points = [(s["task_id"], s["configuration_id"], s["repeat"]) for s in slots.values()]
    if not expected_points or len(points) != len(set(points)) or set(points) != expected_points:
        raise ValueError("Schedule is not the declared task/configuration/repetition product")
    results, attempts = {}, defaultdict(list)
    for entry in batch["attempts"]:
        slot = slots.get(entry["slot_id"])
        if (slot is None or any(entry[key] != value for key, value in slot.items())
                or entry["execution_sha256"] != batch["execution"]["sha256"]):
            raise ValueError("Attempt is outside the frozen schedule")
        previous = attempts[entry["slot_id"]]
        if (entry["attempt"] != len(previous)+1 or entry["attempt"] > manifest["max_infrastructure_retries"]+1
                or previous and previous[-1][0]["state"] != "infrastructure_error"):
            raise ValueError("Unscheduled retry or duplicate measurement")
        report, evaluation = verify_run(root, entry, manifest, batch["execution"]["sha256"]) if entry["report"] else (None, None)
        state = entry["state"]
        if state not in {"running", "measured", "infrastructure_error", "evaluation_error"}:
            raise ValueError("Unknown attempt state")
        if report:
            actual = ("infrastructure_error" if report["termination"] == "infrastructure_error"
                      else "evaluation_error" if report["outcome"] in {"error", "incomplete"} else "measured")
            if actual != state:
                raise ValueError("Attempt state contradicts its run report")
        elif state not in {"running", "infrastructure_error"}:
            raise ValueError("Completed measurement has no report")
        if state == "measured":
            if (report["termination"] not in {"completed", "agent_error", "budget_exhausted"}
                    or report["outcome"] not in {"passed", "failed", "no_submission"}
                    or type(report["task_success"]) is not bool
                    or report["task_success"] != (report["outcome"] == "passed")):
                raise ValueError("Invalid measured result")
            if report["candidate"] is not None:
                if evaluation is None or evaluation["task_success"] != report["task_success"]:
                    raise ValueError("Candidate result has no matching independent evaluation")
            elif report["outcome"] != "no_submission":
                raise ValueError("Missing candidate is not a successful measurement")
            results[entry["slot_id"]] = (report, evaluation)
        attempts[entry["slot_id"]].append((entry, report, evaluation))

    groups = []
    for config_id, agent in manifest["agents"].items():
        environment_groups = sorted({task["environment_group"] for task in manifest["tasks"].values()})
        for environment in environment_groups:
            task_ids = [key for key, task in manifest["tasks"].items() if task["environment_group"] == environment]
            families = Counter(manifest["tasks"][key]["family"] for key in task_ids)
            per_task, all_attempts, measured = {}, [], []
            for task_id in task_ids:
                selected = [s for s in slots.values() if s["task_id"] == task_id and s["configuration_id"] == config_id]
                observed = [results[s["slot_id"]] for s in selected if s["slot_id"] in results]
                task_attempts = [row for s in selected for row in attempts[s["slot_id"]]]
                all_attempts.extend(task_attempts)
                measured.extend(observed)
                successes = sum(r["task_success"] for r, _ in observed)
                physical = sum(e["physical_valid"] is True for _, e in observed if e)
                missing = len(selected)-len(observed)
                metrics = defaultdict(list)
                for report, evaluation in observed:
                    if report["task_success"] and evaluation:
                        for name, metric in evaluation["metrics"].items():
                            if type(metric["value"]) in {int, float} and math.isfinite(metric["value"]):
                                metrics[name].append({"value": metric["value"], "unit": metric["unit"]})
                per_task[task_id] = {
                    "family": manifest["tasks"][task_id]["family"], "scheduled": len(selected),
                    "measured": len(observed), "missing": missing, "successes": successes,
                    "physical_valid": physical,
                    "success_rate": successes/len(selected) if not missing else None,
                    "observed_success_rate": successes/len(observed) if observed else None,
                    "observed_wilson95": wilson(successes, len(observed)),
                    "weight": 1/(len(families)*families[manifest["tasks"][task_id]["family"]]),
                    "successful_metrics": dict(metrics)}
            complete = all(t["missing"] == 0 for t in per_task.values())
            finished_attempts = sum(e["state"] != "running" for e, _, _ in all_attempts)
            groups.append({
                "configuration_id": config_id, "run_kind": agent["run_kind"], "environment_group": environment,
                "environment": manifest["tasks"][task_ids[0]]["environment"],
                "complete": complete, "tasks": per_task, "family_count": len(families),
                "success_rate": sum(t["weight"]*t["success_rate"] for t in per_task.values()) if complete else None,
                "task_equal_success_rate": sum(t["success_rate"] for t in per_task.values())/len(per_task) if complete else None,
                "physical_valid_rate": sum(t["weight"]*t["physical_valid"]/t["scheduled"] for t in per_task.values()) if complete else None,
                "attempts": len(all_attempts), "attempts_finished": finished_attempts,
                "infrastructure_errors": sum(e["state"] == "infrastructure_error" for e, _, _ in all_attempts),
                "evaluation_errors": sum(e["state"] == "evaluation_error" for e, _, _ in all_attempts),
                "infrastructure_error_rate": sum(e["state"] == "infrastructure_error" for e, _, _ in all_attempts)/finished_attempts if finished_attempts else None,
                "termination_counts": dict(Counter(r["termination"] for r, _ in measured)),
                "outcome_counts": dict(Counter(r["outcome"] for r, _ in measured)),
                "resources": {"all_attempts": _resources([r for _, r, _ in all_attempts]),
                              "measured": _resources([r for r, _ in measured]),
                              "successful": _resources([r for r, _ in measured if r["task_success"]]),
                              "unsuccessful": _resources([r for r, _ in measured if not r["task_success"]])}})
    return {"schema_version": 1, "scope": manifest["scope"], "run_kind": "local_batch_development",
            "execution_sha256": batch["execution"]["sha256"], "statistics": manifest["statistics"],
            "statistics_implementation_sha256": Asset(Path(__file__).read_bytes(), "python").sha256,
            "complete": all(group["complete"] for group in groups), "groups": groups}
