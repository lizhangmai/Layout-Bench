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
