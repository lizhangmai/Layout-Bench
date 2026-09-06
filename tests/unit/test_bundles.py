import json

import pytest

from benchmarking.bundles import load_bundle, publish_bundle
from benchmarking.files import Asset
from benchmarking.prepare_support import prepare_support

pytestmark = pytest.mark.unit


def test_bundle_snapshots_verified_files_and_retains_their_identity(tmp_path):
    bundle = publish_bundle({"models/a.lib": Asset(b"frozen model", "spice")}, {"test": True}, tmp_path / "bundle")
    (tmp_path / "bundle/models/a.lib").chmod(0o644)
    (tmp_path / "bundle/models/a.lib").write_text("later change")
    assert bundle.mounted_files()["support/models/a.lib"].content == b"frozen model"
    assert bundle.evidence()["support_manifest"].sha256 == bundle.manifest.sha256
    with pytest.raises(ValueError, match="checksum"):
        load_bundle(tmp_path / "bundle")


@pytest.mark.parametrize("mutation", ["missing", "extra", "symlink"])
def test_bundle_rejects_missing_extra_or_linked_materials(tmp_path, mutation):
    root = tmp_path / "bundle"
    publish_bundle({"a": Asset(b"model", "spice")}, {}, root)
    if mutation == "missing":
        (root / "a").unlink()
    elif mutation == "extra":
        (root / "unreviewed").write_text("unreviewed")
    else:
        (root / "alias").symlink_to(root / "a")
    with pytest.raises((ValueError, FileNotFoundError)):
        load_bundle(root)


def test_support_preparation_only_reads_the_declared_hash_matching_sources(tmp_path):
    model = Asset(b"model source", "spice")
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.lib").write_bytes(model.content)
    (source / "unlisted").write_text("must not be copied")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema_version": 1, "source": {"kind": "synthetic"},
                                  "files": {"models/a.lib": {"path": "model.lib", "sha256": model.sha256,
                                                             "format": "spice"}}}))
    output = tmp_path / "prepared"
    digest = prepare_support(source, profile, output)
    bundle = load_bundle(output)
    assert bundle.manifest.sha256 == digest
    assert set(dict(bundle.files)) == {"models/a.lib", "preparation.json"}
    with pytest.raises(FileExistsError):
        prepare_support(source, profile, output)
    (source / "model.lib").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        prepare_support(source, profile, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()
