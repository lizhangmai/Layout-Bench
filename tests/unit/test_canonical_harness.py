import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _harness_module():
    path = Path(__file__).parents[2] / "examples/agents/canonical_harness.py"
    spec = importlib.util.spec_from_file_location("layout_bench_canonical_harness", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _response(module, **overrides):
    value = {"schema_version": 1, "type": "response", "content": "",
             "tool_calls": [], "stop_reason": "stop"}
    value.update(overrides)
    return value


def test_response_validation_is_order_independent_and_rejects_unknown_tools():
    module = _harness_module()
    call = {"arguments": {"argv": ["true"]}, "name": "run_command", "id": "call-1"}
    result = module.validate_model_response(_response(module, tool_calls=[call], stop_reason="tool_calls"))
    assert result["tool_calls"] == [{"id": "call-1", "name": "run_command", "arguments": {"argv": ["true"]}}]
    with pytest.raises(ValueError, match="Invalid or duplicate"):
        module.validate_model_response(_response(module, tool_calls=[{
            "id": "call-1", "name": "unknown", "arguments": {},
        }], stop_reason="tool_calls"))
    with pytest.raises(ValueError, match="unknown fields"):
        module.validate_model_response(_response(module, extra=True))


def test_adapter_process_uses_jsonl_without_shell_expansion(tmp_path, monkeypatch):
    module = _harness_module()
    monkeypatch.setattr(module, "WORKSPACE", tmp_path)
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    print(json.dumps({'schema_version': 1, 'type': 'response', 'content': request['type'], 'stop_reason': 'stop'}), flush=True)\n"
    )
    with module.AdapterProcess([sys.executable, str(adapter)], timeout=2) as process:
        assert process.request({"schema_version": 1, "type": "request"})["content"] == "request"


def test_workspace_tool_bounds_output_and_timeout(tmp_path, monkeypatch):
    module = _harness_module()
    monkeypatch.setattr(module, "WORKSPACE", tmp_path)
    success = module._tool_result("run_command", {"argv": [sys.executable, "-c", "print('hello')"]})
    assert success["ok"] and success["stdout"] == "hello\n"
    limited = module._tool_result("run_command", {"argv": [sys.executable, "-c", "print('x' * 70000)"]})
    assert not limited["ok"] and limited["truncated"]
    timeout = module._tool_result("run_command", {
        "argv": [sys.executable, "-c", "import time; time.sleep(1)"], "timeout_seconds": .1,
    })
    assert not timeout["ok"] and timeout["timed_out"]
    assert not module._tool_result("run_command", {"argv": ["true"], "timeout_seconds": 31})["ok"]


def test_run_executes_tools_and_submits_through_the_fixed_loop(tmp_path, monkeypatch):
    module = _harness_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(module, "WORKSPACE", workspace)
    descriptor = tmp_path / "task.json"
    descriptor.write_text(json.dumps({"id": "synthetic", "output": {"path": "output/final.gds"}}))
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Create the layout.")
    submit = tmp_path / "submit.py"
    submit.write_text("print('{\"accepted\": true, \"sequence\": 1}')\n")
    monkeypatch.setattr(module, "TASK_DESCRIPTOR", descriptor)
    monkeypatch.setattr(module, "PROMPT", prompt)
    monkeypatch.setattr(module, "SUBMIT", submit)
    adapter = tmp_path / "adapter.py"
    responses = [
        {"schema_version": 1, "type": "response", "content": "", "stop_reason": "tool_calls",
         "tool_calls": [{"id": "write", "name": "run_command", "arguments": {
             "argv": [sys.executable, "-c",
                      "from pathlib import Path; Path('marker').write_text('ok')"]}}]},
        {"schema_version": 1, "type": "response", "content": "", "stop_reason": "tool_calls",
         "tool_calls": [{"id": "submit", "name": "submit_layout", "arguments": {}}]},
        {"schema_version": 1, "type": "response", "content": "done", "stop_reason": "stop"},
    ]
    adapter.write_text(
        "import json, sys\n"
        f"responses = json.loads({json.dumps(responses)!r})\n"
        "for index, line in enumerate(sys.stdin, 1):\n"
        "    json.loads(line)\n"
        "    print(json.dumps(responses[index - 1]), flush=True)\n"
    )
    assert module.run([sys.executable, str(adapter)], max_turns=4, adapter_timeout=2) == "stop"
    assert (workspace / "marker").read_text() == "ok"


def test_run_rejects_adapter_that_never_stops(tmp_path, monkeypatch):
    module = _harness_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(module, "WORKSPACE", workspace)
    descriptor = tmp_path / "task.json"
    descriptor.write_text(json.dumps({"id": "synthetic"}))
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Create the layout.")
    monkeypatch.setattr(module, "TASK_DESCRIPTOR", descriptor)
    monkeypatch.setattr(module, "PROMPT", prompt)
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import json, sys\n"
        "for index, line in enumerate(sys.stdin, 1):\n"
        "    json.loads(line)\n"
        "    response = {'schema_version': 1, 'type': 'response', 'content': '', 'stop_reason': 'tool_calls', 'tool_calls': [{'id': 'call-' + str(index), 'name': 'run_command', 'arguments': {'argv': ['true']}}]}\n"
        "    print(json.dumps(response), flush=True)\n"
    )
    with pytest.raises(TimeoutError, match="max_turns"):
        module.run([sys.executable, str(adapter)], max_turns=1, adapter_timeout=2)
