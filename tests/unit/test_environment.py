import hashlib
import json

import pytest

from benchmarking import environment

pytestmark = pytest.mark.unit


@pytest.fixture
def pdk(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.py").write_bytes(b"# synthetic tool\n")
    (source / "unlisted.gds").write_bytes(b"must not enter the view")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"profile": "synthetic", "files": {
        "tool.py": hashlib.sha256((source / "tool.py").read_bytes()).hexdigest(),
    }}))
    monkeypatch.setattr(environment, "VIEW_MANIFEST", manifest)
    return source, tmp_path / "view"


def test_pdk_view_contains_only_reviewed_files(pdk):
    source, view = pdk
    digest = environment.prepare_pdk(source, view)
    assert environment.verify_pdk(view) == digest
    assert sorted(p.name for p in view.iterdir()) == ["manifest.json", "tool.py"]


def test_bad_source_does_not_publish_partial_view(pdk):
    source, view = pdk
    (source / "tool.py").write_text("modified")
    with pytest.raises(ValueError, match="differs"):
        environment.prepare_pdk(source, view)
    assert not view.exists()


@pytest.mark.parametrize("change", ["modify", "extra", "missing", "symlink"])
def test_changed_view_is_rejected(pdk, change):
    source, view = pdk
    environment.prepare_pdk(source, view)
    tool = view / "tool.py"
    if change == "modify":
        tool.chmod(0o644)
        tool.write_text("changed")
    elif change == "extra":
        (view / "extra.gds").write_bytes(b"unlisted")
    elif change == "missing":
        tool.unlink()
    else:
        (view / "linked").symlink_to(source / "tool.py")
    with pytest.raises(ValueError):
        environment.verify_pdk(view)
