import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from benchmarking.files import Asset
from benchmarking.inference import InferenceConfig, ResponsesGateway

pytestmark = pytest.mark.unit


def _bridge_module():
    path = Path(__file__).parents[2] / "tests/fixtures/agents/inference_bridge.py"
    spec = importlib.util.spec_from_file_location("layout_bench_inference_bridge", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bridge_uses_gateway_framing_and_fixed_model(tmp_path):
    bridge = _bridge_module()
    config = InferenceConfig("https://example.invalid/v1", "test-model", "UNUSED", 2, 10,
                             Asset(b"profile", "text"), "responses")
    gateway = ResponsesGateway(config, transport=lambda path, body, timeout: (
        200, "application/json", b'{"status":"completed","output":[]}'))
    socket_path = tmp_path / "inference.sock"
    gateway.start(socket_path, time.monotonic() + 10)
    try:
        client = bridge.InferenceClient({"socket": str(socket_path), "model": "test-model", "wire_api": "responses"},
                                        timeout=2)
        response = client.create("hello")
        assert response.status == 200
        assert response.content_type == "application/json"
        assert response.json()["status"] == "completed"
        event = gateway.summary()["requests"][0]
        assert event["request_bytes"] > 0
    finally:
        gateway.stop()


def test_bridge_rejects_invalid_response_frame(tmp_path):
    bridge = _bridge_module()
    socket_path = tmp_path / "inference.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(socket_path))
    server.listen(1)

    def serve():
        connection, _ = server.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(b'{"status":200,"type":"application/json","bytes":4}\nno')
            # The client must not treat a short body as a valid response.

    worker = threading.Thread(target=serve)
    worker.start()
    try:
        client = bridge.InferenceClient({"socket": str(socket_path), "model": "test-model", "wire_api": "responses"},
                                        timeout=2)
        with pytest.raises(ConnectionError, match="response body"):
            client.create("hello")
    finally:
        server.close()
        worker.join(timeout=2)


@pytest.mark.parametrize("path", ["/files", "/responses?other=1"])
def test_bridge_rejects_non_gateway_paths(path):
    bridge = _bridge_module()
    client = bridge.InferenceClient({"socket": "/tmp/unused.sock", "model": "test-model"})
    with pytest.raises(ValueError, match="Unsupported inference path"):
        client.request(path, {})
