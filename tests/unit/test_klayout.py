import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarking.klayout import validate_drc_waivers

pytestmark = pytest.mark.unit


def test_drc_waiver_schema_keeps_case_local_marker_scope():
    waivers = validate_drc_waivers([{
        "category": "'NBL.b'",
        "cell": "DIFF_COMPARATOR",
        "markers": ["edge-pair: marker-a", "edge-pair: marker-b"],
        "reason": "Known upstream ring construction",
    }])
    assert waivers == [{
        "category": "'NBL.b'",
        "cell": "DIFF_COMPARATOR",
        "markers": ["edge-pair: marker-a", "edge-pair: marker-b"],
        "reason": "Known upstream ring construction",
    }]


@pytest.mark.parametrize("change", [
    {"unknown": "field"},
    {"markers": []},
    {"markers": ["same", "same"]},
    {"reason": ""},
])
def test_drc_waiver_schema_rejects_ambiguous_entries(change):
    entry = {
        "category": "'NBL.b'",
        "cell": "DIFF_COMPARATOR",
        "markers": ["edge-pair: marker"],
        "reason": "Known upstream ring construction",
    }
    entry.update(change)
    with pytest.raises((TypeError, ValueError)):
        validate_drc_waivers([entry])


def test_drc_waiver_schema_rejects_duplicate_marker_across_entries():
    entry = {
        "category": "'NBL.b'",
        "cell": "DIFF_COMPARATOR",
        "markers": ["edge-pair: marker"],
        "reason": "Known upstream ring construction",
    }
    with pytest.raises(ValueError, match="Duplicate"):
        validate_drc_waivers([entry, dict(entry)])


@pytest.mark.parametrize("primary,extra,expected", [
    ("passed", "failed", "failed"),
    ("failed", "passed", "failed"),
    ("failed", "error", "error"),
    ("passed", "passed", "passed"),
])
def test_all_drc_decks_contribute_to_one_gate(monkeypatch, primary, extra, expected):
    # Exercise orchestration without substituting a real rule-check result.
    monkeypatch.setitem(sys.modules, "klayout", SimpleNamespace(db=None, rdb=None))
    module = runpy.run_path(str(Path(__file__).resolve().parents[2] / "benchmarking/klayout_runner.py"))
    main = module["main"]
    monkeypatch.setitem(main.__globals__, "artifact", lambda config: "")
    calls = []

    def run_deck(config, suffix, used):
        calls.append((config["deck"], suffix))
        status = primary if not suffix else extra
        count = int(status == "failed")
        return status, "test failure" if status != "passed" else "", {
            "violations": count, "unwaived_violations": count,
            "waived_violations": 0, "by_category": {"rule": count},
            "unwaived_by_category": {"rule": count},
        }

    monkeypatch.setitem(main.__globals__, "run_deck", run_deck)
    status, _, details = main({"check": "drc", "deck": "main.drc", "required_categories": ["rule"],
                              "additional_decks": [{"deck": "extra.drc", "required_categories": ["rule"]}]})
    assert calls == [("main.drc", ""), ("extra.drc", "-1")]
    assert status == expected
    assert details["violations"] == int(primary == "failed") + int(extra == "failed")
    assert [entry["report"] for entry in details["decks"]] == ["report.db", "report-1.db"]
