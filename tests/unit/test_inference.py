import json
import socket
import time
from pathlib import Path

import pytest

from benchmarking.files import Asset
from benchmarking.inference import (
    InferenceConfig,
    InferenceGateway,
    ResponsesGateway,
    WireRequest,
    available_wire_adapters,
    load_inference_config,
    normalize_usage,
    register_wire_adapter,
    unregister_wire_adapter,
    validate_harness_wire,
    validate_request,
)

pytestmark = pytest.mark.unit


class FakeWireAdapter:
    """Deterministic second wire family used only at the public seam."""

    id = "fake-json"

    def validate_request(self, path, body, model):
        if path != "/generate":
            raise ValueError("fake adapter only supports /generate")
        value = json.loads(body)
        if value.get("model") != model:
            raise ValueError("model mismatch")
        return json.dumps(value, separators=(",", ":")).encode()

    def prepare_request(self, path, body, model, credential):
        return WireRequest("POST", path, {"X-Fake-Credential": credential,
                                           "Content-Type": "application/json"})

    def response_semantics(self, path, content_type, body):
        value = json.loads(body)
        if value.get("status") != "done":
            raise ValueError("fake response is not terminal")
        return {"outcome": "completed", "reason": None,
                "usage": normalize_usage(value.get("usage"))}


def _fake_config():
    return InferenceConfig("https://example.invalid/v1", "fake-model", "UNUSED", 2, 10,
                           Asset(b"fake-profile", "text"), "fake-json")


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
        validate_request(path, json.dumps({"model": "test-model", **extra}).encode(), "test-model", "responses")


def test_request_bound_usage_and_no_error_body_exposure():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
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


def test_summary_separates_forwarded_denied_failed_and_truncated_requests():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 3, 10,
                             Asset(b"profile", "text"), "responses")
    responses = iter([
        b'{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}',
        b'{"status":"failed","error":{"code":"upstream"}}',
        (b'{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},'
         b'"usage":{"input_tokens":3,"output_tokens":4}}'),
    ])
    gateway = InferenceGateway(config, transport=lambda *args: (200, "application/json", next(responses)))
    gateway.deadline = time.monotonic() + 10
    for _ in range(3):
        assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 200
    assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 429
    summary = gateway.summary()
    assert summary["request_counts"] == {
        "forwarded": 3, "denied": 1, "failed": 1, "truncated": 1,
        "content_filtered": 0, "cancelled": 0,
    }
    assert summary["denied_reasons"] == {"request_budget_exhausted": 1}
    assert summary["usage"]["input_tokens"] is None
    assert summary["usage_observed"]["input_tokens"] == {"known": 2, "missing": 1}
    assert summary["wall_seconds"] >= 0
    assert all(event["elapsed_seconds"] >= 0 for event in summary["requests"])


def test_declared_observable_token_and_gateway_time_budgets_are_provider_neutral():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 5, 10,
                             Asset(b"profile", "text"), "responses",
                             max_input_tokens=2, max_output_tokens=3, max_wall_seconds=30)
    gateway = InferenceGateway(
        config,
        transport=lambda *args: (200, "application/json",
                                 b'{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}'),
    )
    gateway.deadline = time.monotonic() + 10
    assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 200
    assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 429
    summary = gateway.summary()
    assert summary["budget"] == {
        "max_requests": 5, "max_input_tokens": 2,
        "max_output_tokens": 3, "max_wall_seconds": 30,
    }
    assert summary["denied_reasons"] == {"input_token_budget_exhausted": 1}
    assert summary["limit_reached"] is True


def test_no_forwarded_requests_are_not_classified_as_model_usage():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
    gateway = ResponsesGateway(config, transport=lambda *args: pytest.fail("Denied request was forwarded"))
    gateway.deadline = time.monotonic()+10
    assert gateway.request("/responses", b'{"model":"test-model","input":[{"file_id":"remote"}]}')[0] == 400
    assert gateway.summary()["requests"] == []
    assert gateway.summary()["run_kind"] == "offline_cli_development"

    gateway._transport = lambda *args: (200, "application/json", b'{"status":"completed"}')
    assert gateway.request("/responses", b'{"model":"test-model"}')[0] == 200
    assert gateway.summary()["run_kind"] == "model_protocol_test"


def test_credential_stays_out_of_public_identity_and_profile_requires_tls(tmp_path, monkeypatch):
    source = Path(tmp_path / "profile.toml")
    source.write_text('''schema_version = 1
wire_api = "responses"
base_url = "https://example.invalid/v1"
model = "test-model"
api_key_env = "LAYOUT_BENCH_TEST_KEY"
max_requests = 2
request_timeout_seconds = 5
max_input_tokens = 100
max_output_tokens = 50
max_wall_seconds = 120
''')
    config = load_inference_config(source)
    monkeypatch.setenv(config.api_key_env, "unique-secret-value")
    gateway = ResponsesGateway(config)
    assert "unique-secret-value" not in json.dumps(gateway.public)
    assert gateway.public["socket"] == "/protocol/inference.sock"
    assert gateway.public["max_input_tokens"] == 100
    assert gateway.public["max_output_tokens"] == 50
    assert gateway.public["max_wall_seconds"] == 120
    source.write_text(source.read_text().replace("https://", "http://"))
    with pytest.raises(ValueError, match="HTTPS"):
        load_inference_config(source)


def test_profile_rejects_unknown_wire_adapter(tmp_path):
    source = Path(tmp_path / "profile.toml")
    source.write_text('''schema_version = 1
wire_api = "unknown"
base_url = "https://example.invalid/v1"
model = "test-model"
api_key_env = "LAYOUT_BENCH_TEST_KEY"
max_requests = 2
request_timeout_seconds = 5
''')
    with pytest.raises(ValueError, match="wire_api"):
        load_inference_config(source)


def test_profile_requires_an_explicit_wire_family(tmp_path):
    source = Path(tmp_path / "profile.toml")
    source.write_text('''schema_version = 1
base_url = "https://example.invalid/v1"
model = "test-model"
api_key_env = "LAYOUT_BENCH_TEST_KEY"
max_requests = 2
request_timeout_seconds = 5
''')
    with pytest.raises(ValueError, match="wire_api"):
        load_inference_config(source)


def test_registered_fake_wire_adapter_owns_wire_semantics_and_transport_is_deterministic():
    adapter = FakeWireAdapter()
    register_wire_adapter(adapter)
    try:
        assert "fake-json" in available_wire_adapters()
        calls = []

        def transport(path, body, timeout):
            calls.append((path, json.loads(body), timeout))
            return 200, "application/json", b'{"status":"done","usage":{"input_tokens":4}}'

        gateway = InferenceGateway(_fake_config(), transport=transport)
        gateway.deadline = time.monotonic() + 10
        status, content_type, body = gateway.request("/generate", b'{"model":"fake-model"}')

        assert (status, content_type, body) == (200, "application/json",
                                                  b'{"status":"done","usage":{"input_tokens":4}}')
        assert calls[0][0] == "/generate" and calls[0][1] == {"model": "fake-model"}
        assert gateway.wire_adapter.prepare_request("/generate", body, "fake-model", "secret").headers == {
            "X-Fake-Credential": "secret", "Content-Type": "application/json"}
        assert gateway.summary()["wire_api"] == "fake-json"
        assert gateway.summary()["usage"] == {
            "input_tokens": 4, "output_tokens": None, "cached_input_tokens": None,
            "reasoning_output_tokens": None, "cost": None,
        }
    finally:
        unregister_wire_adapter("fake-json")


def test_registry_rejects_replacing_or_removing_the_builtin_adapter():
    register_wire_adapter(FakeWireAdapter())
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_wire_adapter(FakeWireAdapter())
    finally:
        unregister_wire_adapter("fake-json")
    with pytest.raises(ValueError, match="cannot be removed"):
        unregister_wire_adapter("responses")


def test_harness_wire_declaration_must_match_gateway():
    validate_harness_wire(None, "responses")
    validate_harness_wire("responses", "responses")
    with pytest.raises(ValueError, match="wire_api"):
        validate_harness_wire("other", "responses")


def test_http_200_failed_event_is_infrastructure_error():
    response = b'data: {"type":"response.failed","response":{"status":"failed","error":{"code":"server_error"}}}\n\n'
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
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
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
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
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
    gateway = ResponsesGateway(config, transport=lambda *args: (200, "text/event-stream", body))
    gateway.deadline = time.monotonic() + 10
    gateway.request("/responses", b'{"model":"test-model"}')
    assert gateway.summary()["infrastructure_error"]


def test_multiline_sse_and_standalone_compaction():
    from benchmarking.inference import response_semantics

    body = b': keepalive\r\nevent: response.completed\r\ndata: {"type":"response.completed",\r\ndata: "response":{"status":"completed"}}\r\n\r\n'
    assert response_semantics("/responses", "text/event-stream", body, "responses")["outcome"] == "completed"
    request = validate_request("/responses/compact", b'{"model":"test-model","input":[],"store":true}',
                               "test-model", "responses")
    assert "store" not in json.loads(request)
    result = response_semantics("/responses/compact", "application/json",
                                b'{"object":"response.compaction","output":[],"usage":{"input_tokens":1}}',
                                "responses")
    assert result["outcome"] == "completed" and result["usage"]["input_tokens"] == 1


def test_function_tool_schema_may_use_resource_like_field_names():
    body = {
        "model": "test-model",
        "tools": [{
            "type": "function",
            "name": "load_asset",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "file_url": {"type": "string"},
                    "image_url": {"type": "string"},
                },
            },
        }],
    }
    request = validate_request("/responses", json.dumps(body).encode(), "test-model", "responses")
    assert json.loads(request)["tools"] == body["tools"]


def test_malformed_http_200_response_keeps_upstream_status_and_hides_body():
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
    gateway = ResponsesGateway(config, transport=lambda *args: (
        200, "application/json", b'{"status":"in_progress","secret":"must-not-forward"}'))
    gateway.deadline = time.monotonic() + 10
    status, content_type, body = gateway.request("/responses", b'{"model":"test-model"}')
    assert status == 200
    assert content_type == "application/json"
    assert body == b'{"error":"Inference response failed validation"}'
    event = gateway.summary()["requests"][0]
    assert event["status"] == 200
    assert event["outcome"] == "protocol_or_transport_error"
    assert gateway.summary()["infrastructure_error"]


def test_socket_handler_closes_cleanly_on_recursive_json_header(tmp_path):
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 1, 10,
                             Asset(b"profile", "text"), "responses")
    gateway = ResponsesGateway(config, transport=lambda *args: pytest.fail("Malformed header reached gateway"))
    path = tmp_path / "inference.sock"
    gateway.start(path, time.monotonic() + 10)
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(path))
            nested = b"[" * 1000 + b"]" * 1000
            client.sendall(b'{"bytes":0,"path":' + nested + b'}\n')
            assert client.recv(1) == b""
    finally:
        gateway.stop()


def test_request_and_response_persist_before_forwarding(tmp_path, monkeypatch):
    from benchmarking.recorder import RecordingError, RunRecorder

    recorder = RunRecorder(tmp_path / "run")
    def transport(path, body, timeout):
        journal = [json.loads(line) for line in (recorder.root / "events.jsonl").read_text().splitlines()]
        request = journal[-1]
        assert request["kind"] == "inference.request"
        assert (recorder.root / request["data"]["request"]["path"]).read_bytes() == body
        return 200, "application/json", b'{"status":"completed","output":[]}'
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 2, 10,
                             Asset(b"profile", "text"), "responses")
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
            response_semantics("/responses", "text/event-stream", completed + tail, "responses")
    unicode_message = '{"type":"response.completed","response":{"status":"completed","text":"a\u2028b"}}'
    assert response_semantics("/responses", "text/event-stream", ('data: '+unicode_message+'\n\n').encode(),
                              "responses")["outcome"] == "completed"
