"""Frozen local task × configuration × repetition plans with isolated workers."""

import json
import os
import random
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
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


def _resolve_plan(plan, *, session_factory, gateway_factory, toolchain_loader):
    """Load all solve/evaluation inputs before any task receives a prompt."""
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
        gateway = gateway_factory(profile) if profile else None
        agents.append({"id": entry["id"], "config": config, "resources": resources,
                       "profile": profile, "image_id": session.image_id,
                       "inference_identity": gateway.public if gateway else None,
                       "run_kind": "offline_cli_development" if gateway is None else
                           "model_protocol_test" if gateway.is_test else "model_cli_development"})
    return tasks, agents


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


def _run_slots(plan, manifest, batch, recorder, tasks, agents, *, runner, session_factory,
               gateway_factory, policy, concurrency, slots=None, start_attempts=None):
    """Run each frozen slot, serializing evidence writes but not independent solves."""
    task_map = {entry["task"].id: entry for entry in tasks}
    agent_map = {entry["id"]: entry for entry in agents}
    state_lock = threading.RLock()
    slots = list(manifest["schedule"] if slots is None else slots)
    start_attempts = start_attempts or {}

    def run_slot(slot):
        task_entry, agent_entry = task_map[slot["task_id"]], agent_map[slot["configuration_id"]]
        first_attempt = start_attempts.get(slot["slot_id"], 0) + 1
        for attempt in range(first_attempt, plan.max_infrastructure_retries + 2):
            if policy is not None:
                policy.check_time()
            verify_framework(manifest["framework"])
            if {op: b.identity for op, b in task_entry["backends"].items()} != task_entry["identities"]:
                raise ValueError("Evaluation environment changed after freezing")
            context = {"execution_sha256": batch["execution"]["sha256"], **slot, "attempt": attempt}
            path = f'runs/{slot["slot_id"]}/attempt-{attempt}'
            entry = {**context, "path": path, "state": "running", "report": None}
            with state_lock:
                batch["attempts"].append(entry)
                recorder.event("attempt.started", **context)
                recorder.save(batch, filename="batch.json")
            gateway = None
            session = None
            try:
                gateway = gateway_factory(agent_entry["profile"]) if agent_entry["profile"] else None
                session = session_factory(agent_entry["config"].image)
                if session.image_id != agent_entry["image_id"]:
                    raise ValueError("Agent image changed after freezing")
                if gateway and gateway.public != agent_entry["inference_identity"]:
                    raise ValueError("Inference environment differs from frozen identity")
                result = runner(task_entry["task"], agent_entry["config"], agent_entry["resources"],
                                task_entry["backends"], recorder.root / path, inference=gateway,
                                session=session, execution=context)
                report_path = recorder.root / path / "run.json"
                raw = read_file(report_path.parent, report_path.name)
                if json.loads(raw) != result:
                    raise ValueError("Returned result differs from its persisted report")
                entry["report"] = {**Asset(raw, "json").identity(), "path": path + "/run.json"}
                entry["state"] = ("infrastructure_error" if result["termination"] == "infrastructure_error"
                                  else "evaluation_error" if result["outcome"] in {"error", "incomplete"}
                                  else "measured")
            except Exception as error:  # noqa: BLE001 -- retain category, not credential-bearing details
                entry.update(state="infrastructure_error", exception_type=type(error).__name__)
            if entry["report"]:
                verify_run(recorder.root, entry, manifest, batch["execution"]["sha256"])
            verify_framework(manifest["framework"])
            if {op: b.identity for op, b in task_entry["backends"].items()} != task_entry["identities"]:
                raise ValueError("Evaluation environment changed during execution")
            with state_lock:
                recorder.event("attempt.stopped", **entry)
                recorder.save(batch, filename="batch.json")
            if entry["state"] != "infrastructure_error":
                break

    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="layout-bench")
    futures = [executor.submit(run_slot, slot) for slot in slots]
    try:
        for future in futures:
            future.result()
    except BaseException:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)


def execute_plan(plan, destination, *, runner=run_agent, session_factory=DockerSession,
                 gateway_factory=InferenceGateway, toolchain_loader=load_toolchain,
                 policy=None, prepare_only=False, concurrency=1):
    """Preflight/freeze everything before the first solver receives a task.

    Injected implementations are for trusted adapters and deterministic tests.
    Development scope and qualified labels do not grant formal admission.
    """
    if prepare_only and policy is not None:
        raise ValueError("Preparation does not consume an admission policy")
    if policy is not None:
        policy.check_time()
    if type(concurrency) is not int or concurrency <= 0:
        raise ValueError("concurrency must be a positive integer")
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    tasks, agents = _resolve_plan(plan, session_factory=session_factory,
                                  gateway_factory=gateway_factory,
                                  toolchain_loader=toolchain_loader)

    recorder = RunRecorder(destination)
    archive = recorder.archive
    manifest = {"schema_version": 1, "id": plan.id, "scope": plan.scope,
                "run_kind": "local_batch_development", "plan": archive(plan.source),
                "framework": snapshot_framework(archive), "host": host_identity(concurrency=concurrency),
                "repetitions": plan.repetitions, "order": plan.order, "seed": plan.seed,
                "max_infrastructure_retries": plan.max_infrastructure_retries,
                "concurrency": concurrency,
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
            "image_id": entry["image_id"], "command": list(config.command),
            "environment": config.environment,
            "budget": {key: getattr(config, key) for key in ("wall_seconds", "cpus", "memory_mb", "pids", "workspace_mb")},
            "files": {key: archive(a) for key, a in config.files.items()},
            "resources": {key: archive(a) for key, a in entry["resources"].items()},
            "inference": {"source": archive(profile.source), "identity": entry["inference_identity"],
                          "model": profile.model, "base_url": profile.base_url,
                          "max_requests": profile.max_requests,
                          "request_timeout_seconds": profile.request_timeout_seconds,
                          "max_input_tokens": profile.max_input_tokens,
                          "max_output_tokens": profile.max_output_tokens,
                          "max_wall_seconds": profile.max_wall_seconds} if profile else None}
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
    _run_slots(plan, manifest, batch, recorder, tasks, agents, runner=runner,
               session_factory=session_factory, gateway_factory=gateway_factory,
               policy=policy, concurrency=concurrency)
    # The batch report is still running while the provisional statistics are
    # computed; ``finish`` seals the event journal and publishes the final
    # phase immediately afterwards. External callers must only summarize a
    # finished batch.
    summary = summarize_batch(recorder.root, allow_in_progress=True)
    batch.update(summary=summary, termination="completed", outcome="complete" if summary["complete"] else "incomplete")
    recorder.finish(batch, filename="batch.json", kind="batch.finished")
    atomic_write(recorder.root / "summary.json", json_asset(summary).content)
    return batch


def _validate_resolved_manifest(plan, tasks, agents, manifest, *, concurrency, gateway_factory):
    """Bind a recovery invocation to the original frozen task/configuration set."""
    if (manifest.get("id") != plan.id or manifest.get("scope") != plan.scope
            or manifest.get("repetitions") != plan.repetitions
            or manifest.get("order") != plan.order or manifest.get("seed") != plan.seed
            or manifest.get("max_infrastructure_retries") != plan.max_infrastructure_retries
            or manifest.get("concurrency", 1) != concurrency):
        raise ValueError("Recovery plan differs from frozen execution conditions")
    if manifest.get("schedule") != _schedule(plan, tasks, agents):
        raise ValueError("Recovery schedule differs from frozen execution conditions")
    for entry in tasks:
        task = entry["task"]
        frozen = manifest["tasks"].get(task.id)
        if (frozen is None or frozen["task_sha256"] != task.digest
                or frozen["source"]["sha256"] != entry["source"].sha256
                or frozen["toolchain"]["sha256"] != entry["toolchain"].sha256
                or frozen["backends"] != entry["identities"]
                or {key: value["sha256"] for key, value in frozen["inputs"].items()}
                != {item.role: item.sha256 for item in task.inputs}):
            raise ValueError("Recovery task inputs differ from frozen execution conditions")
    for entry in agents:
        config, profile = entry["config"], entry["profile"]
        frozen = manifest["agents"].get(entry["id"])
        if frozen is None:
            raise ValueError("Recovery agent differs from frozen execution conditions")
        if (frozen["agent_id"] != config.id or frozen["source"]["sha256"] != config.source.sha256
                or frozen["image"] != config.image or frozen["image_id"] != entry["image_id"]
                or frozen["command"] != list(config.command) or frozen["environment"] != config.environment
                or frozen["harness"] != config.harness.identity()
                or frozen["budget"] != {key: getattr(config, key)
                                         for key in ("wall_seconds", "cpus", "memory_mb", "pids", "workspace_mb")}
                or {key: value["sha256"] for key, value in frozen["files"].items()}
                != {key: value.sha256 for key, value in config.files.items()}
                or {key: value["sha256"] for key, value in frozen["resources"].items()}
                != {key: value.sha256 for key, value in entry["resources"].items()}):
            raise ValueError("Recovery agent differs from frozen execution conditions")
        if profile is None:
            if frozen["inference"] is not None:
                raise ValueError("Recovery inference configuration differs from frozen conditions")
        else:
            gateway = gateway_factory(profile)
            if (frozen["inference"] is None
                    or frozen["inference"]["source"]["sha256"] != profile.source.sha256
                    or frozen["inference"]["identity"] != gateway.public):
                raise ValueError("Recovery inference configuration differs from frozen conditions")


def resume_plan(plan, destination, *, runner=run_agent, session_factory=DockerSession,
                gateway_factory=InferenceGateway, toolchain_loader=load_toolchain,
                concurrency=None):
    """Resume an interrupted batch in place, retaining every old attempt/evidence blob."""
    root = Path(destination).absolute()
    batch = json.loads(read_file(root, "batch.json"))
    if (batch.get("schema_version") != 1 or batch.get("run_kind") != "local_batch_development"
            or batch.get("phase") != "running" or batch.get("summary") is not None):
        raise ValueError("Only an unfinished batch can be resumed")
    execution_raw = read_file(root, "execution.json")
    execution_ref = batch.get("execution")
    if not isinstance(execution_ref, dict) or Asset(execution_raw, "json").sha256 != execution_ref.get("sha256"):
        raise ValueError("Frozen execution manifest is unavailable or corrupt")
    manifest = json.loads(execution_raw)
    if manifest.get("run_kind") != "local_batch_development":
        raise ValueError("Unsupported frozen execution manifest")
    frozen_concurrency = manifest.get("concurrency", 1)
    if concurrency is None:
        concurrency = frozen_concurrency
    if type(concurrency) is not int or concurrency <= 0 or concurrency != frozen_concurrency:
        raise ValueError("Recovery cannot change frozen concurrency")
    tasks, agents = _resolve_plan(plan, session_factory=session_factory,
                                  gateway_factory=gateway_factory,
                                  toolchain_loader=toolchain_loader)
    _validate_resolved_manifest(plan, tasks, agents, manifest, concurrency=concurrency,
                                gateway_factory=gateway_factory)
    recorder = RunRecorder.resume(root)
    execution_sha = execution_ref["sha256"]
    for attempt in batch["attempts"]:
        if attempt.get("state") != "running":
            continue
        report_path = root / attempt["path"] / "run.json"
        if attempt.get("report") is None and report_path.is_file():
            raw = read_file(report_path.parent, report_path.name)
            attempt["report"] = {**Asset(raw, "json").identity(), "path": attempt["path"] + "/run.json"}
        if attempt.get("report") is not None:
            try:
                recovered, _ = verify_run(root, attempt, manifest, execution_sha)
                attempt["state"] = ("infrastructure_error" if recovered["termination"] == "infrastructure_error"
                                     else "evaluation_error" if recovered["outcome"] in {"error", "incomplete"}
                                     else "measured")
            except (TypeError, ValueError, OSError, KeyError):
                attempt["report"] = None
                attempt.update(state="infrastructure_error", exception_type="interrupted")
        else:
            attempt.update(state="infrastructure_error", exception_type="interrupted")
        recorder.event("attempt.recovered", path=attempt["path"], state=attempt["state"])
    recorder.save(batch, filename="batch.json")
    attempts_by_slot = {}
    for attempt in batch["attempts"]:
        attempts_by_slot.setdefault(attempt["slot_id"], []).append(attempt)
    selected, starts = [], {}
    for slot in manifest["schedule"]:
        previous = attempts_by_slot.get(slot["slot_id"], [])
        if previous and previous[-1]["state"] in {"measured", "evaluation_error"}:
            continue
        if len(previous) < plan.max_infrastructure_retries + 1:
            selected.append(slot)
            starts[slot["slot_id"]] = len(previous)
    recorder.event("batch.resumed", execution_sha256=execution_sha,
                   slots=[slot["slot_id"] for slot in selected])
    recorder.save(batch, filename="batch.json")
    _run_slots(plan, manifest, batch, recorder, tasks, agents, runner=runner,
               session_factory=session_factory, gateway_factory=gateway_factory,
               policy=None, concurrency=concurrency, slots=selected, start_attempts=starts)
    summary = summarize_batch(root, allow_in_progress=True)
    batch.update(summary=summary, termination="completed", outcome="complete" if summary["complete"] else "incomplete")
    recorder.finish(batch, filename="batch.json", kind="batch.finished")
    atomic_write(root / "summary.json", json_asset(summary).content)
    return batch
