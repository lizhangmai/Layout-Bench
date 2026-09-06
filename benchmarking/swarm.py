"""Frozen local task × configuration × repetition plans; serial independent sessions."""

import json
import os
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .admission import conditions, freeze_admission, reserve
from .agent import run_agent
from .bundles import load_bundle
from .evaluation import identifier
from .files import Asset, keys, read_file, text
from .inference import InferenceGateway, load_inference_config, validate_harness_wire
from .model_config import load_run_config
from .provenance import host_identity, json_asset, snapshot_framework, verify_framework
from .recorder import RunRecorder, atomic_write
from .report import summarize_batch, verify_run
from .session import DockerSession
from .tasks import load_task
from .toolchains import load_toolchain


@dataclass(frozen=True)
class RunPlan:
    id: str
    scope: str
    repetitions: int
    order: str
    seed: int
    max_infrastructure_retries: int
    tasks: tuple[dict, ...]
    agents: tuple[dict, ...]
    source: Asset


def load_plan(path):
    """Resolve references relative to the plan; do not start tools or read credentials."""
    path = Path(path).absolute()
    source = Asset(read_file(path.parent, path.name), "toml")
    data = tomllib.loads(source.content.decode())
    keys(data, {"schema_version", "id", "scope", "repetitions", "order", "seed",
                "max_infrastructure_retries", "tasks", "agents"}, set(), "run plan")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported run plan version")
    identifier(data["id"])
    if data["scope"] not in {"public_development", "hidden_development", "synthetic"}:
        raise ValueError("Plans currently support local development scopes only")
    if data["order"] not in {"interleaved", "shuffled"}:
        raise ValueError("Unknown scheduling order")
    for name, minimum in (("repetitions", 1), ("seed", 0), ("max_infrastructure_retries", 0)):
        if type(data[name]) is not int or data[name] < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    for group in ("tasks", "agents"):
        if not isinstance(data[group], list) or not data[group]:
            raise ValueError(f"Run plan needs a nonempty {group} list")
        seen = set()
        for entry in data[group]:
            required = {"config", "toolchain"} if group == "tasks" else {"id", "config"}
            keys(entry, required, set() if group == "tasks" else {"resources", "inference"}, group)
            if group == "agents":
                identifier(entry["id"])
                if entry["id"] in seen:
                    raise ValueError("Duplicate agent configuration id")
                seen.add(entry["id"])
            for name in entry.keys() - {"id"}:
                # These are trusted maintainer references, not paths supplied by an Agent.
                target = Path(os.path.abspath(path.parent / text(entry[name], name)))
                if target.resolve(strict=True) != target:
                    raise ValueError("Plan references must not contain symlinks")
                entry[name] = target
    return RunPlan(*(data[k] for k in ("id", "scope", "repetitions", "order", "seed",
                                     "max_infrastructure_retries")), tuple(data["tasks"]), tuple(data["agents"]), source)


def _schedule(plan, tasks, agents):
    schedule = [{"task_id": task["task"].id, "configuration_id": agent["id"], "repeat": repeat}
                for repeat in range(1, plan.repetitions + 1) for task in tasks for agent in agents]
    if plan.order == "shuffled":
        random.Random(plan.seed).shuffle(schedule)
    return [{"slot_id": f"s{index:06d}", **entry} for index, entry in enumerate(schedule, 1)]


def execute_plan(plan, destination, *, runner=run_agent, session_factory=DockerSession,
                 gateway_factory=InferenceGateway, toolchain_loader=load_toolchain,
                 policy=None, prepare_only=False):
    """Preflight/freeze everything before the first solver receives a task.

    Injected implementations are for trusted adapters and deterministic tests.
    Development scope and qualified labels do not grant formal admission.
    """
    if prepare_only and policy is not None:
        raise ValueError("Preparation does not consume an admission policy")
    if policy is not None:
        policy.check_time()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    tasks, agents, task_ids = [], [], set()
    for entry in plan.tasks:
        task = load_task(entry["config"])
        if task.id in task_ids:
            raise ValueError("Duplicate task id in run plan")
        task_ids.add(task.id)
        if task.evaluation is None or task.evaluation.mode != "post_layout":
            raise ValueError("Batch tasks require post_layout evaluation")
        source = Asset(read_file(entry["config"].parent, entry["config"].name), "toml")
        if source.sha256 != task.digest:
            raise ValueError("Task configuration changed during preflight")
        toolchain = Asset(read_file(entry["toolchain"].parent, entry["toolchain"].name), "toml")
        backends = toolchain_loader(entry["toolchain"])
        if read_file(entry["toolchain"].parent, entry["toolchain"].name) != toolchain.content:
            raise ValueError("Toolchain configuration changed during preflight")
        if not {j.operation for j in task.evaluation.jobs} <= backends.keys():
            raise ValueError("Missing batch evaluation backend bindings")
        identities = json.loads(json_asset({op: backend.identity for op, backend in sorted(backends.items())}).content)
        tasks.append({"task": task, "backends": backends, "identities": identities,
                      "source": source, "toolchain": toolchain})
    for entry in plan.agents:
        config = load_run_config(entry["config"])
        resources = {}
        if "resources" in entry:
            bundle = load_bundle(entry["resources"])
            resources = {**dict(bundle.files), "manifest.json": bundle.manifest}
        profile = load_inference_config(entry["inference"]) if "inference" in entry else None
        if profile:
            validate_harness_wire(config.harness.wire_api, profile.wire_api)
        session = session_factory(config.image)
        # Capture credential availability now, but create a fresh gateway for every attempt.
        gateway = gateway_factory(profile) if profile else None
        agents.append({"id": entry["id"], "config": config, "resources": resources,
                       "profile": profile, "session": session, "inference_identity": gateway.public if gateway else None,
                       "run_kind": "offline_cli_development" if gateway is None else
                           "model_protocol_test" if gateway.is_test else "model_cli_development"})

    recorder = RunRecorder(destination)
    archive = recorder.archive
    manifest = {"schema_version": 1, "id": plan.id, "scope": plan.scope,
                "run_kind": "local_batch_development", "plan": archive(plan.source),
                "framework": snapshot_framework(archive), "host": host_identity(),
                "repetitions": plan.repetitions, "order": plan.order, "seed": plan.seed,
                "max_infrastructure_retries": plan.max_infrastructure_retries,
                "statistics": {"weighting": "family_equal_then_task_equal", "confidence": 0.95,
                               "per_task_interval": "wilson", "aggregate_interval": None,
                               "generalization_interval": None},
                "tasks": {}, "agents": {}, "schedule": _schedule(plan, tasks, agents)}
    for entry in tasks:
        task = entry["task"]
        manifest["tasks"][task.id] = {
            "task_sha256": task.digest, "family": task.family, "environment": task.environment,
            "environment_group": json_asset({"environment": task.environment, "backends": entry["identities"]}).sha256,
            "source": archive(entry["source"]), "description": archive(task.evaluation_inputs()["task"]),
            "inputs": {item.role: archive(Asset(item.content, item.format)) for item in task.inputs},
            "toolchain": archive(entry["toolchain"]), "backends": entry["identities"],
            "operations": sorted({job.operation for job in task.evaluation.jobs})}
    for entry in agents:
        config, profile = entry["config"], entry["profile"]
        manifest["agents"][entry["id"]] = {
            "agent_id": config.id, "source": archive(config.source), "image": config.image,
            "harness": config.harness.identity(),
            "run_kind": entry["run_kind"],
            "image_id": entry["session"].image_id, "command": list(config.command),
            "environment": config.environment,
            "budget": {key: getattr(config, key) for key in ("wall_seconds", "cpus", "memory_mb", "pids", "workspace_mb")},
            "files": {key: archive(a) for key, a in config.files.items()},
            "resources": {key: archive(a) for key, a in entry["resources"].items()},
            "inference": {"source": archive(profile.source), "identity": entry["inference_identity"],
                          "model": profile.model, "base_url": profile.base_url,
                          "max_requests": profile.max_requests,
                          "request_timeout_seconds": profile.request_timeout_seconds} if profile else None}
    if policy is not None:
        manifest["admission"] = freeze_admission(policy, manifest, archive)
    frozen = archive(json_asset(manifest))
    atomic_write(recorder.root / "execution.json", json_asset(manifest).content, 0o400)
    batch = {"schema_version": 1, "run_kind": "local_batch_development", "phase": "running",
             "execution": frozen, "events": {"path": "events.jsonl", "schema_version": 1},
             "attempts": [], "summary": None, "termination": None, "outcome": None}
    if prepare_only:
        batch.update(phase="prepared", outcome="prepared", conditions_sha256=json_asset(conditions(manifest)).sha256)
        recorder.event("batch.prepared", execution_sha256=frozen["sha256"], conditions_sha256=batch["conditions_sha256"])
        recorder.save(batch, filename="batch.json")
        return batch
    if policy is not None:
        batch["admission_reservation"] = reserve(policy, frozen["sha256"])
        recorder.event("admission.reserved", **batch["admission_reservation"])
    recorder.save(batch, filename="batch.json")
    recorder.event("batch.started", execution_sha256=frozen["sha256"])
    task_map = {entry["task"].id: entry for entry in tasks}
    agent_map = {entry["id"]: entry for entry in agents}
    for slot in manifest["schedule"]:
        task_entry, agent_entry = task_map[slot["task_id"]], agent_map[slot["configuration_id"]]
        for attempt in range(1, plan.max_infrastructure_retries + 2):
            if policy is not None:
                policy.check_time()
            verify_framework(manifest["framework"])
            if {op: b.identity for op, b in task_entry["backends"].items()} != task_entry["identities"]:
                raise ValueError("Evaluation environment changed after freezing")
            context = {"execution_sha256": frozen["sha256"], **slot, "attempt": attempt}
            path = f'runs/{slot["slot_id"]}/attempt-{attempt}'
            entry = {**context, "path": path, "state": "running", "report": None}
            batch["attempts"].append(entry)
            recorder.event("attempt.started", **context)
            recorder.save(batch, filename="batch.json")
            gateway = gateway_factory(agent_entry["profile"]) if agent_entry["profile"] else None
            try:
                if gateway and gateway.public != agent_entry["inference_identity"]:
                    raise ValueError("Inference environment differs from frozen identity")
                result = runner(task_entry["task"], agent_entry["config"], agent_entry["resources"],
                                task_entry["backends"], recorder.root / path, inference=gateway,
                                session=agent_entry["session"], execution=context)
                report_path = recorder.root / path / "run.json"
                raw = read_file(report_path.parent, report_path.name)
                if json.loads(raw) != result:
                    raise ValueError("Returned result differs from its persisted report")
                entry["report"] = {**Asset(raw, "json").identity(), "path": path + "/run.json"}
                entry["state"] = ("infrastructure_error" if result["termination"] == "infrastructure_error"
                                  else "evaluation_error" if result["outcome"] in {"error", "incomplete"}
                                  else "measured")
            except Exception as error:  # noqa: BLE001 -- retain every failed attempt without exposing exceptions/credentials
                entry.update(state="infrastructure_error", exception_type=type(error).__name__)
            if entry["report"]:
                verify_run(recorder.root, entry, manifest, frozen["sha256"])
            verify_framework(manifest["framework"])
            if {op: b.identity for op, b in task_entry["backends"].items()} != task_entry["identities"]:
                raise ValueError("Evaluation environment changed during execution")
            recorder.event("attempt.stopped", **entry)
            recorder.save(batch, filename="batch.json")
            if entry["state"] != "infrastructure_error":
                break
    summary = summarize_batch(recorder.root)
    batch.update(summary=summary, termination="completed", outcome="complete" if summary["complete"] else "incomplete")
    recorder.finish(batch, filename="batch.json", kind="batch.finished")
    atomic_write(recorder.root / "summary.json", json_asset(summary).content)
    return batch
