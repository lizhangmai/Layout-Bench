import json
import time
from pathlib import Path

import pytest

from benchmarking.files import Asset
from benchmarking.inference import (
    InferenceConfig,
    ResponsesGateway,
    load_inference_config,
    validate_request,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path,extra", [
    ("/files", {}), ("/responses?url=https://elsewhere", {}),
    ("/responses", {"model": "another"}), ("/responses", {"tools": [{"type": "web_search"}]}),
    ("/responses", {"tools": [{"type": "namespace", "tools": [{"type": "mcp"}]}]}),
    ("/responses", {"input": [{"image_url": "https://elsewhere/a.png"}]}),
    ("/responses", {"input": [{"file_id": "file_x"}]}),
    ("/responses", {"background": True}), ("/responses", {"previous_response_id": "someone-elses-response"}),
])
def test_gateway_rejects_other_destinations_models_and_remote_tools(path, extra):
    with pytest.raises(ValueError):
        validate_request(path, json.dumps({"model": "test-model", **extra}).encode(), "test-model")


def test_request_bound_usage_and_no_error_body_exposure():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10, Asset(b"profile", "text"))
    def transport(path, body, timeout):
        assert json.loads(body)["store"] is False
        return 200, "application/json", b'{"status":"completed","usage":{"input_tokens":10,"output_tokens":3}}'
    gateway = ResponsesGateway(config, transport=transport)
    gateway.deadline = time.monotonic()+10
    assert gateway.request("/responses", b'{"model":"test-model","store":true}')[0] == 200
    assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 429
    assert gateway.summary()["usage"]["input_tokens"] == 10
    assert gateway.summary()["usage"]["output_tokens"] == 3
    assert gateway.summary()["usage"]["cached_input_tokens"] is None
    assert gateway.summary()["limit_reached"]

    def broken(*args):
        raise OSError("secret-key-in-exception")
    gateway = ResponsesGateway(config, transport=broken)
    gateway.deadline = time.monotonic()+10
    status, _, body = gateway.request("/responses", b'{"model":"test-model"}')
    assert status == 502 and b"secret" not in body
    assert "secret" not in json.dumps(gateway.summary())
    assert gateway.summary()["usage"]["input_tokens"] is None


def test_credential_stays_out_of_public_identity_and_profile_requires_tls(tmp_path, monkeypatch):
    source = Path(tmp_path / "profile.toml")
    source.write_text('''schema_version = 1
base_url = "https://example.invalid/v1"
model = "test-model"
api_key_env = "LAYOUT_BENCH_TEST_KEY"
max_requests = 2
request_timeout_seconds = 5
''')
    config = load_inference_config(source)
    monkeypatch.setenv(config.api_key_env, "unique-secret-value")
    gateway = ResponsesGateway(config)
    assert "unique-secret-value" not in json.dumps(gateway.public)
    source.write_text(source.read_text().replace("https://", "http://"))
    with pytest.raises(ValueError, match="HTTPS"):
        load_inference_config(source)


def test_http_200_failed_event_is_infrastructure_error():
    response = b'data: {"type":"response.failed","response":{"status":"failed","error":{"code":"server_error"}}}\n\n'
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10, Asset(b"profile", "text"))
    gateway = ResponsesGateway(config, transport=lambda *args: (200, "text/event-stream", response))
    gateway.deadline = time.monotonic() + 10
    gateway.request("/responses", b'{"model":"test-model"}')
    assert gateway.summary()["infrastructure_error"] is True


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("state,details,outcome,infra", [
    ("completed", {}, "completed", False),
    ("failed", {"error": {"code": "server_error"}}, "service_error", True),
    ("incomplete", {"incomplete_details": {"reason": "max_output_tokens"}}, "budget_truncated", False),
    ("incomplete", {"incomplete_details": {"reason": "content_filter"}}, "content_filtered", False),
    ("incomplete", {"incomplete_details": {"reason": "server_error"}}, "incomplete_error", True),
    ("incomplete", {}, "incomplete_error", True),
    ("in_progress", {}, "protocol_or_transport_error", True),
])
def test_response_semantics_and_usage(stream, state, details, outcome, infra):
    response = {"status": state, **details, "usage": {"input_tokens": 9, "output_tokens": 2}}
    body = json.dumps(response).encode()
    content_type = "application/json"
    if stream:
        body = b'data: ' + json.dumps({"type": f"response.{state}", "response": response}).encode() + b'\n\n'
        content_type = "text/event-stream; charset=utf-8"
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10, Asset(b"profile", "text"))
    gateway = ResponsesGateway(config, transport=lambda *args: (200, content_type, body))
    gateway.deadline = time.monotonic() + 10
    gateway.request("/responses", b'{"model":"test-model"}')
    gateway.stop()
    summary = gateway.summary()
    assert summary["infrastructure_error"] is infra
    assert summary["requests"][0]["outcome"] == outcome
    if state != "in_progress":
        assert summary["usage"]["input_tokens"] == 9


@pytest.mark.parametrize("body", [
    b'data: {"type":"response.created"}\n\n',
    b'data: [DONE]\n\n',
    b'data: {"type":"response.completed","response":{"status":"completed"}}\n',
    b'data: {"type":"response.completed","response":{"status":"failed"}}\n\n',
    b'data: {"type":"error","code":"server_error"}\n\n',
    b'data: not-json\n\n',
    b'data: []\n\n',
])
def test_non_success_sse_cannot_be_scored_as_a_model_failure(body):
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10, Asset(b"profile", "text"))
    gateway = ResponsesGateway(config, transport=lambda *args: (200, "text/event-stream", body))
    gateway.deadline = time.monotonic() + 10
    gateway.request("/responses", b'{"model":"test-model"}')
    assert gateway.summary()["infrastructure_error"]


def test_multiline_sse_and_standalone_compaction():
    from benchmarking.inference import response_semantics

    body = b': keepalive\r\nevent: response.completed\r\ndata: {"type":"response.completed",\r\ndata: "response":{"status":"completed"}}\r\n\r\n'
    assert response_semantics("/responses", "text/event-stream", body)["outcome"] == "completed"
    request = validate_request("/responses/compact", b'{"model":"test-model","input":[]}', "test-model")
    assert "store" not in json.loads(request)
    result = response_semantics("/responses/compact", "application/json",
                                b'{"object":"response.compaction","output":[],"usage":{"input_tokens":1}}')
    assert result["outcome"] == "completed" and result["usage"]["input_tokens"] == 1


def test_request_and_response_persist_before_forwarding(tmp_path, monkeypatch):
    from benchmarking.recorder import RecordingError, RunRecorder

    recorder = RunRecorder(tmp_path / "run")
    def transport(path, body, timeout):
        journal = [json.loads(line) for line in (recorder.root / "events.jsonl").read_text().splitlines()]
        request = journal[-1]
        assert request["kind"] == "inference.request"
        assert (recorder.root / request["data"]["request"]["path"]).read_bytes() == body
        return 200, "application/json", b'{"status":"completed","output":[]}'
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 2, 10, Asset(b"profile", "text"))
    gateway = ResponsesGateway(config, transport=transport)
    gateway.recorder = recorder
    gateway.deadline = time.monotonic() + 10
    result = gateway.request("/responses", b'{"model":"test-model"}')
    journal = [json.loads(line) for line in (recorder.root / "events.jsonl").read_text().splitlines()]
    assert journal[-1]["kind"] == "inference.result"
    assert (recorder.root / journal[-1]["data"]["response"]["path"]).read_bytes() == result[2]
    # A failure to record the next request must prevent any transport call.
    monkeypatch.setattr(recorder, "event", lambda *a, **kw: (_ for _ in ()).throw(RecordingError("disk full")))
    monkeypatch.setattr(gateway, "_transport", lambda *a: pytest.fail("Unrecorded request was sent"))
    with pytest.raises(RecordingError):
        gateway.request("/responses", b'{"model":"test-model"}')


def test_conflicting_or_nonterminal_sse_tail_is_rejected():
    from benchmarking.inference import response_semantics

    completed = b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
    for tail in (completed, b'data: {"type":"response.created"}\n\n'):
        with pytest.raises(ValueError, match="terminal"):
            response_semantics("/responses", "text/event-stream", completed + tail)
    unicode_message = '{"type":"response.completed","response":{"status":"completed","text":"a\u2028b"}}'
    assert response_semantics("/responses", "text/event-stream", ('data: '+unicode_message+'\n\n').encode())["outcome"] == "completed"
