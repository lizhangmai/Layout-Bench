"""Run one offline CLI session, then independently evaluate its accepted snapshot."""

import json
import time
from pathlib import Path

from .evaluate import run_evaluation
from .files import Asset
from .harnesses import PROCESS_FEEDBACK_CAPABILITY
from .inference import validate_harness_wire
from .recorder import RecordingError, RunRecorder
from .session import DockerSession, task_message


def run_agent(task, config, resources, backends, destination: Path, *, inference=None, session=None, execution=None):
    if task.evaluation is None or task.evaluation.mode != "post_layout":
        raise ValueError("Agent runs require a post_layout task plan")
    operations = {job.operation for job in task.evaluation.jobs}
    if not operations <= backends.keys():
        raise ValueError("Missing evaluation backend bindings")
    if inference:
        validate_harness_wire(config.harness.wire_api, inference.config.wire_api)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    session = session or DockerSession(config.image)
    execution = json.loads(json.dumps(execution, allow_nan=False))
    recorder = RunRecorder(destination)
    archive = recorder.archive
    message = task_message(task, config)
    report = {"schema_version": 2, "events": {"path": "events.jsonl", "schema_version": 1}, "run_kind": "offline_cli_development", "task_sha256": task.digest,
              "agent_id": config.id, "harness": config.harness.identity(),
              "configuration": archive(config.source), "execution": execution,
              "command": list(config.command), "public_environment": config.environment,
              "prompt": archive(Asset(message.encode(), "text")),
              "task": archive(task.evaluation_inputs()["task"]),
              "inputs": {item.role: archive(Asset(item.content, item.format)) for item in task.inputs},
              "agent_files": {name: archive(a) for name, a in config.files.items()},
              "resources": {name: archive(a) for name, a in resources.items()},
              "implementation": {name: archive(Asset(Path(__file__).with_name(name).read_bytes(), "python"))
                                 for name in ("agent.py", "session.py", "snapshot.py", "submit.py", "process_check.py",
                                              "model_config.py", "harnesses.py", "recorder.py", "recording.py")},
              "usage": {"input_tokens": None, "output_tokens": None, "cost": None},
              "phase": "running", "outcome": None, "task_success": None, "evaluation": None}
    def save():
        recorder.save(report)

    if inference:
        inference.recorder = recorder
        report.update(run_kind="model_protocol_test" if inference.is_test else "model_cli_development",
                      inference_profile=archive(inference.config.source), inference=inference.public)
        report["implementation"]["inference.py"] = archive(Asset(Path(__file__).with_name("inference.py").read_bytes(), "python"))
    save()
    recorder.event("run.started", task_sha256=task.digest, agent_id=config.id)
    feedback_enabled = PROCESS_FEEDBACK_CAPABILITY in config.harness.capabilities

    def process_feedback(candidate, sequence):
        feedback_root = destination / "feedback" / f"check-{sequence}"
        feedback_root.parent.mkdir(parents=True, exist_ok=True)
        evaluated = run_evaluation(
            task.evaluation,
            {**task.evaluation_inputs(), "candidate": candidate},
            backends,
            feedback_root,
            task_sha256=task.digest,
        )
        raw = (feedback_root / "report.json").read_bytes()
        return {
            "report": evaluated,
            "report_path": f"feedback/check-{sequence}/report.json",
            "report_ref": archive(Asset(raw, "json")),
        }

    session_kwargs = {"inference": inference, "recorder": recorder}
    if feedback_enabled:
        session_kwargs["feedback"] = process_feedback
    result = session.run(task, config, resources, message, **session_kwargs)
    if inference:
        if inference.shutdown_incomplete:
            raise RecordingError("Inference worker did not stop; run evidence remains incomplete")
        report["inference"] = inference.summary()
        # An inference profile alone does not prove model usage.  A request
        # that was denied before forwarding must remain an offline probe, while
        # deterministic transports retain the protocol-test label once they
        # actually receive a request.
        report["run_kind"] = report["inference"]["run_kind"]
        report["usage"] = report["inference"]["usage"]
        if report["inference"]["infrastructure_error"]:
            result.termination, result.reason = "infrastructure_error", "Inference service failed; see request statuses"
        elif report["inference"]["limit_reached"] and result.termination != "infrastructure_error":
            result.termination, result.reason = "budget_exhausted", "Inference request budget exhausted"
    report.update(phase="stopped", termination=result.termination, reason=result.reason,
                  elapsed_seconds=result.elapsed_seconds, exit_code=result.exit_code,
                  submissions=result.submissions, console=archive(result.console),
                  console_truncated=result.console_truncated, environment=result.environment,
                  candidate=archive(result.candidate) if result.candidate is not None else None)
    if feedback_enabled:
        report["process_feedback"] = {"capability": PROCESS_FEEDBACK_CAPABILITY,
                                      "checks": result.process_feedback}
    save()  # Preserve submission/termination even if independent evaluation cannot finish.
    if result.candidate is not None:
        started = time.monotonic()
        try:
            evaluated = run_evaluation(task.evaluation,
                                      {**task.evaluation_inputs(), "candidate": result.candidate},
                                      backends, destination / "evaluation", task_sha256=task.digest)
            report.update(evaluation={"path": "evaluation/report.json",
                                     "sha256": Asset((destination/"evaluation/report.json").read_bytes(), "json").sha256},
                          outcome=evaluated["outcome"], task_success=evaluated["task_success"])
        except Exception as error:  # noqa: BLE001 -- retain the accepted snapshot on infrastructure failure
            report.update(outcome="error", task_success=None, evaluation_error=str(error))
        report["evaluation_seconds"] = time.monotonic() - started
    else:
        report.update(outcome="no_submission", task_success=False)
    if result.termination == "infrastructure_error":
        report.update(outcome="error", task_success=None)
    recorder.finish(report)
    return report
