"""Task preparation, offline CLI sessions and configurable independent evaluation."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from benchmarking.admission import export_batch, load_policy
from benchmarking.agent import run_agent
from benchmarking.bundles import load_bundle
from benchmarking.evaluate import run_evaluation
from benchmarking.evaluation import identifier, parse_evaluation
from benchmarking.files import Asset, read_file
from benchmarking.inference import (
    InferenceGateway,
    load_inference_config,
    validate_harness_wire,
)
from benchmarking.model_config import load_run_config
from benchmarking.recorder import recover_submissions
from benchmarking.report import summarize_batch
from benchmarking.swarm import execute_plan, load_plan
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain


def _run_summary(report, output):
    """Return a compact, actionable summary for the ``run`` command.

    The durable evaluation report remains the source of truth.  The command
    line should nevertheless tell a first-time user which gate failed without
    requiring them to open a second JSON file manually.
    """
    summary = {"report": str(output / "run.json"),
               **{key: report[key] for key in
                  ("termination", "reason", "outcome", "task_success", "candidate")}}
    if report.get("inference") is not None:
        summary["inference_requests"] = len(report["inference"].get("requests", []))
    evaluation_path = output / "evaluation/report.json"
    if not evaluation_path.is_file():
        return summary
    try:
        evaluation = json.loads(evaluation_path.read_text())
    except (OSError, ValueError):
        return summary
    failures = []
    for job_id, job in evaluation.get("jobs", {}).items():
        if job.get("status") in {"failed", "error"}:
            failures.append({"kind": "job", "id": job_id, "status": job["status"],
                             "reason": job.get("reason")})
    for metric_id, metric in evaluation.get("metrics", {}).items():
        if metric.get("status") in {"failed", "error"}:
            failures.append({"kind": "metric", "id": metric_id, "status": metric["status"],
                             "reason": metric.get("reason")})
    if failures:
        summary["failures"] = failures
    return summary


def _inference_preflight(profile, config, credential_present):
    """Describe a model profile without making a provider request."""
    return {
        "status": "ready" if credential_present else "missing_credential",
        "model_call": False,
        "endpoint": profile.base_url,
        "model": profile.model,
        "wire_api": profile.wire_api,
        "credential_env": profile.api_key_env,
        "credential_present": credential_present,
        "harness": config.harness.identity() if config else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    task_parser = subcommands.add_parser("task", help="Validate a task and show its I/O")
    task_parser.add_argument("config", type=Path, help="Path to task.toml")
    task_parser.add_argument("--materialize", type=Path, help="New directory for verified inputs")
    evaluate_parser = subcommands.add_parser("evaluate", help="Evaluate a GDS with a task's declared plan")
    evaluate_parser.add_argument("config", type=Path)
    evaluate_parser.add_argument("candidate", type=Path)
    characterize_parser = subcommands.add_parser("characterize", help="Run a standalone measurement plan; no layout score")
    characterize_parser.add_argument("plan", type=Path)
    characterize_parser.add_argument("--input", action="append", default=[], metavar="ROLE:FORMAT=PATH")
    run_parser = subcommands.add_parser("run", help="Run an offline CLI and evaluate its explicit submission")
    run_parser.add_argument("config", type=Path, help="Task configuration")
    run_parser.add_argument("--agent", type=Path, required=True, help="Frozen offline CLI configuration")
    run_parser.add_argument("--resources", type=Path, help="Verified support bundle mounted at /resources")
    run_parser.add_argument("--inference", type=Path, help="Fixed HTTPS inference profile; credential stays on host")
    for command in (evaluate_parser, characterize_parser, run_parser):
        command.add_argument("--toolchain", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True, help="New directory for report and evidence")
    recover_parser = subcommands.add_parser("recover", help="Verify durable submissions without resuming or scoring a run")
    recover_parser.add_argument("directory", type=Path)
    batch_parser = subcommands.add_parser("batch", help="Execute a frozen local development run plan")
    batch_parser.add_argument("plan", type=Path)
    batch_parser.add_argument("--output", type=Path, required=True)
    batch_parser.add_argument("--prepare-only", action="store_true", help="Freeze conditions for operator review without starting solvers")
    batch_parser.add_argument("--policy", type=Path, help="Operator-reviewed admission policy; requires an independent pin")
    batch_parser.add_argument("--policy-sha256", help="Trusted operator's policy digest")
    summary_parser = subcommands.add_parser("summarize", help="Verify and recompute internal batch statistics")
    summary_parser.add_argument("directory", type=Path)
    inference_parser = subcommands.add_parser(
        "inference-check", help="Validate an inference profile and host credential without making a model call"
    )
    inference_parser.add_argument("profile", type=Path)
    inference_parser.add_argument("--agent", type=Path, help="Optional harness configuration to check wire compatibility")
    export_parser = subcommands.add_parser("export", help="Emit only preapproved aggregate fields from an admitted batch")
    export_parser.add_argument("directory", type=Path)
    export_parser.add_argument("--policy-sha256", required=True, help="Trusted operator's original policy digest")
    args = parser.parse_args()
    try:
        if args.command == "batch":
            if bool(args.policy) != bool(args.policy_sha256):
                raise ValueError("--policy and --policy-sha256 must be supplied together by the operator")
            policy = load_policy(args.policy, args.policy_sha256) if args.policy else None
            batch = execute_plan(load_plan(args.plan), args.output, policy=policy, prepare_only=args.prepare_only)
            result = {"report": str(args.output / "batch.json"), "outcome": batch["outcome"]}
            if args.prepare_only:
                result["conditions_sha256"] = batch["conditions_sha256"]
            elif policy is None:
                result["summary"] = batch["summary"]
            print(json.dumps(result, indent=2, allow_nan=False))
            if batch["outcome"] not in {"complete", "prepared"}:
                parser.exit(2)
            return
        if args.command == "export":
            try:
                released = export_batch(args.directory, args.policy_sha256)
                encoded = json.dumps(released, indent=2, allow_nan=False)
            except Exception:  # noqa: BLE001 -- export errors must not expose internal paths or task data
                parser.exit(2, "Layout-Bench export rejected; an operator must inspect internal evidence.\n")
            print(encoded)
            return
        if args.command == "summarize":
            print(json.dumps(summarize_batch(args.directory), indent=2, allow_nan=False))
            return
        if args.command == "recover":
            print(json.dumps(recover_submissions(args.directory), indent=2, allow_nan=False))
            return
        if args.command == "inference-check":
            profile = load_inference_config(args.profile)
            config = load_run_config(args.agent) if args.agent else None
            if config:
                validate_harness_wire(config.harness.wire_api, profile.wire_api)
            result = _inference_preflight(profile, config, bool(os.environ.get(profile.api_key_env)))
            print(json.dumps(result, indent=2, allow_nan=False))
            if not result["credential_present"]:
                parser.exit(1)
            return
        if args.command == "task":
            task = load_task(args.config)
            if args.materialize:
                task.materialize(args.materialize)
            print(json.dumps(task.description(), ensure_ascii=False, indent=2))
            return
        if args.command == "run":
            resources = {}
            if args.resources:
                bundle = load_bundle(args.resources)
                resources = {**dict(bundle.files), "manifest.json": bundle.manifest}
            config = load_run_config(args.agent)
            profile = load_inference_config(args.inference) if args.inference else None
            if profile:
                validate_harness_wire(config.harness.wire_api, profile.wire_api)
            report = run_agent(load_task(args.config), config, resources,
                               load_toolchain(args.toolchain), args.output,
                               inference=InferenceGateway(profile) if profile else None)
            print(json.dumps(_run_summary(report, args.output), indent=2))
            if report["outcome"] != "passed":
                parser.exit(2 if report["outcome"] in {"error", "incomplete"} else 1)
            return
        task_digest = None
        if args.command == "evaluate":
            task = load_task(args.config)
            plan = task.evaluation
            if plan is None or plan.mode == "characterization":
                raise ValueError("Task needs a physical or post_layout evaluation plan")
            candidate = args.candidate.absolute()
            if candidate.stat().st_size > task.output.max_bytes:
                raise ValueError("Candidate exceeds the configured GDS size limit")
            inputs = task.evaluation_inputs()
            inputs["candidate"] = Asset(read_file(candidate.parent, candidate.name), "gds")
            task_digest = task.digest
        else:
            path = args.plan.absolute()
            plan = parse_evaluation(read_file(path.parent, path.name))
            if plan.mode != "characterization":
                raise ValueError("characterize requires mode = 'characterization'")
            inputs = {}
            for argument in args.input:
                name, separator, path = argument.partition("=")
                role, colon, file_format = name.partition(":")
                if not separator or not colon or not path or not file_format:
                    raise ValueError("--input requires ROLE:FORMAT=PATH")
                ref = f"input:{identifier(role)}"
                if ref in inputs:
                    raise ValueError(f"Duplicate input: {role}")
                source = Path(path).absolute()
                inputs[ref] = Asset(read_file(source.parent, source.name), file_format)
        report = run_evaluation(plan, inputs, load_toolchain(args.toolchain), args.output,
                                task_sha256=task_digest)
    except (TypeError, ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Layout-Bench command failed: {error}\n")
    print(json.dumps({"report": str(args.output / "report.json"), **{
        key: report[key] for key in ("mode", "outcome", "physical_valid", "specs_pass", "task_success", "metrics")
    }}, indent=2, allow_nan=False))
    if report["outcome"] != "passed":
        parser.exit(1 if report["outcome"] == "failed" else 2)


if __name__ == "__main__":
    main()
