"""Small command-line summaries remain useful without replacing durable reports."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("layout_bench_main", ROOT / "main.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_run_summary = _MODULE._run_summary
_inference_preflight = _MODULE._inference_preflight


pytestmark = [pytest.mark.unit, pytest.mark.acceptance, pytest.mark.acceptance_fast]


def test_run_summary_surfaces_failed_gates_and_inference_count(tmp_path):
    output = tmp_path / "run"
    evaluation = output / "evaluation"
    evaluation.mkdir(parents=True)
    (evaluation / "report.json").write_text(json.dumps({
        "jobs": {
            "artifact": {"status": "passed"},
            "lvs": {"status": "failed", "reason": "LVS mismatch"},
        },
        "metrics": {
            "delay": {"status": "failed", "reason": "upper bound exceeded"},
        },
    }))
    summary = _run_summary({
        "termination": "completed", "reason": "", "outcome": "failed", "task_success": False,
        "candidate": {"sha256": "abc"},
        "inference": {"requests": [{"sequence": 1}, {"sequence": 2}]},
    }, output)
    assert summary["inference_requests"] == 2
    assert summary["failures"] == [
        {"kind": "job", "id": "lvs", "status": "failed", "reason": "LVS mismatch"},
        {"kind": "metric", "id": "delay", "status": "failed", "reason": "upper bound exceeded"},
    ]


def test_run_summary_does_not_hide_missing_evaluation(tmp_path):
    summary = _run_summary({
        "termination": "completed", "reason": "", "outcome": "no_submission", "task_success": False,
        "candidate": None,
    }, tmp_path / "run")
    assert summary == {
        "report": str(tmp_path / "run/run.json"),
        "termination": "completed", "reason": "", "outcome": "no_submission",
        "task_success": False, "candidate": None,
    }


def test_inference_preflight_never_reports_a_model_call():
    class Profile:
        base_url = "https://example.invalid/v1"
        model = "test-model"
        wire_api = "responses"
        api_key_env = "LAYOUT_BENCH_TEST_KEY"

    assert _inference_preflight(Profile(), None, False) == {
        "status": "missing_credential",
        "model_call": False,
        "endpoint": "https://example.invalid/v1",
        "model": "test-model",
        "wire_api": "responses",
        "credential_env": "LAYOUT_BENCH_TEST_KEY",
        "credential_present": False,
        "harness": None,
    }
