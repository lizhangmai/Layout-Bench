"""Actual installed Codex against a deterministic Responses fixture, no paid inference."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarking.agent import run_agent
from benchmarking.files import Asset
from benchmarking.inference import InferenceConfig, ResponsesGateway
from benchmarking.model_config import load_run_config
from benchmarking.recorder import RunRecorder, recover_submissions
from benchmarking.session import DockerSession, task_message
from benchmarking.tasks import load_task

IMAGE = os.environ.get("LAYOUT_BENCH_TEST_IMAGE", "layout-bench-agent:local")

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def events(output, index):
    response = {"id": f"resp_test_{index}", "object": "response", "status": "completed", "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}}
    payloads = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}}]
    for i, item in enumerate(output):
        payloads.extend([{"type": "response.output_item.added", "output_index": i, "item": item},
                         {"type": "response.output_item.done", "output_index": i, "item": item}])
    payloads.append({"type": "response.completed", "response": response})
    return b"".join(b"event: "+p["type"].encode()+b"\ndata: "+json.dumps(p).encode()+b"\n\n" for p in payloads)


def test_real_codex_exec_tools_submission_and_gateway_isolation(tmp_path):
    requests = []
    def respond(path, raw, timeout):
        request = json.loads(raw)
        requests.append(request)
        if len(requests) == 1:
            # The command is a test fixture supplied by a deterministic model endpoint.
            # It validates model->CLI->shell->submission, without solving any layout task.
            command = "mkdir -p output; printf 'model-protocol-test' > output/final.gds; python -I /protocol/submit.py"
            output = [{"type": "function_call", "id": "fc_test", "call_id": "call_test",
                       "name": "exec_command", "arguments": json.dumps({"cmd": command, "yield_time_ms": 1000})}]
        else:
            output = [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "Protocol fixture submitted.", "annotations": []}]}]
        return 200, "text/event-stream", events(output, len(requests))

    task = load_task(ROOT/"tasks/academy-tgate/task.toml")
    config = replace(load_run_config(ROOT/"examples/agents/codex.toml"), image=IMAGE, wall_seconds=30)
    profile = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 4, 20, Asset(b"test profile", "text"))
    gateway = ResponsesGateway(profile, transport=respond)
    recorder = RunRecorder(tmp_path / "run")
    result = DockerSession(config.image).run(task, config, {}, task_message(task, config),
                                             inference=gateway, recorder=recorder)
    assert result.termination == "completed", result.console.content.decode(errors="replace")
    assert result.candidate is not None, (result.console.content, requests, gateway.summary())
    assert result.candidate.content == b"model-protocol-test"
    assert len(requests) == 2
    assert all(r["model"] == "test-model" and r["store"] is False for r in requests)
    assert gateway.summary()["usage"]["input_tokens"] == 200
    assert b'"type":"turn.completed"' in result.console.content
    assert result.environment["network"] == "none"
    journal = [json.loads(line) for line in (recorder.root / "events.jsonl").read_text().splitlines()]
    assert len([e for e in journal if e["kind"] == "inference.result"]) == 2
    second_request = gateway.summary()["requests"][1]["request"]
    frozen_request = json.loads((recorder.root / second_request["path"]).read_bytes())
    assert frozen_request == requests[1]
    assert any(item.get("type") == "function_call_output" for item in frozen_request["input"])
    assert recover_submissions(recorder.root)["candidate"]["sha256"] == result.candidate.sha256


@pytest.mark.parametrize("status,kind,body", [
    (503, "application/json", b'{"error":"unavailable"}'),
    (200, "text/event-stream", b'data: {"type":"response.failed","response":{"status":"failed","error":{"code":"server_error"}}}\n\n'),
])
def test_inference_service_failure_is_not_a_model_failure(tmp_path, status, kind, body):
    task = load_task(ROOT/"tasks/academy-tgate/task.toml")
    config = replace(load_run_config(ROOT/"examples/agents/codex.toml"), image=IMAGE, wall_seconds=10)
    profile = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 4, 5, Asset(b"test", "text"))
    gateway = ResponsesGateway(profile, transport=lambda *args: (status, kind, body))
    backends = {job.operation: object() for job in task.evaluation.jobs}
    report = run_agent(task, config, {}, backends, tmp_path/"run", inference=gateway)
    assert report["run_kind"] == "model_protocol_test"
    assert report["termination"] == "infrastructure_error"
    assert report["outcome"] == "error" and report["task_success"] is None
    assert report["candidate"] is None and report["evaluation"] is None
    assert report["usage"]["input_tokens"] is None
