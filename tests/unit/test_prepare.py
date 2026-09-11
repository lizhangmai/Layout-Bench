"""Source export resolution expands the case-owned files and the PDK profile."""

import hashlib

import pytest

from benchmarking.prepare import resolve_source_files

pytestmark = pytest.mark.unit


def _pdk_manifest(path, files):
    entries = "".join(
        f'[profiles.symbols.files."{target}"]\npath = "{source}"\n'
        f'sha256 = "{hashlib.sha256(content).hexdigest()}"\nformat = "xschem"\n\n'
        for target, (source, content) in files.items())
    path.write_text(f'schema_version = 1\n\n[source]\n'
                    f'repository = "https://example.invalid/pdk"\ncommit = "{"0" * 40}"\n\n{entries}')


def _case(path, *, profile="../../../pdk.toml#symbols", files=True):
    own = ('[[source_export.files]]\ncheckout = "case"\npath = "source/demo.sch"\n'
           'target = "demo.sch"\nsha256 = "a378667699cf81eff1a49baa7a075836d5641b95836a4063810d06f11a303aef"\n'
           if files else "")
    empty = "" if files else "files = []\n"
    reference = f'pdk_profile = "{profile}"\n' if profile is not None else ""
    path.write_text(f'schema_version = 2\nkind = "layout_case"\nid = "demo"\ntitle = "Demo"\n'
                    f'status = "candidate"\n\n[origin]\ncheckout = "third_party/demo"\n'
                    f'commit = "{"0" * 40}"\nlicense = "MIT"\n\n'
                    f'[[sources]]\nid = "demo.sch"\npath = "sch/demo.sch"\nrole = "design"\n'
                    f'format = "xschem"\nsha256 = "{"f" * 64}"\n\n'
                    f'[source_export]\ntool = "xschem-lvs"\n{reference}'
                    f'schematic = "demo.sch"\nnetlist = "circuit.cdl"\n{empty}\n{own}')


def test_resolve_expands_the_referenced_pdk_profile(tmp_path):
    _pdk_manifest(tmp_path / "pdk.toml", {"sg13g2_pr/nmos.sym": ("pdk/nmos.sym", b"nmos"),
                                          "sg13g2_pr/pmos.sym": ("pdk/pmos.sym", b"pmos")})
    case = tmp_path / "cases/demo/case.toml"
    case.parent.mkdir(parents=True)
    _case(case, profile="../../pdk.toml#symbols")
    spec, entries, profile = resolve_source_files(case)
    assert spec["schematic"] == "demo.sch"
    assert [entry["target"] for entry in entries] == [
        "demo.sch", "sg13g2_pr/nmos.sym", "sg13g2_pr/pmos.sym"]
    assert [entry["checkout"] for entry in entries] == ["case", "pdk", "pdk"]
    assert entries[1]["path"] == "pdk/nmos.sym"
    assert entries[1]["sha256"] == hashlib.sha256(b"nmos").hexdigest()
    assert profile is not None and profile.format == "json"


def test_resolve_keeps_a_manifest_without_profile_as_is(tmp_path):
    case = tmp_path / "case.toml"
    _case(case, profile=None)
    _, entries, profile = resolve_source_files(case)
    assert [entry["checkout"] for entry in entries] == ["case"]
    assert profile is None


def test_resolve_rejects_a_malformed_profile_reference(tmp_path):
    case = tmp_path / "case.toml"
    _case(case, profile="pdk.toml")
    with pytest.raises(ValueError, match="must name a manifest profile"):
        resolve_source_files(case)


def test_resolve_rejects_an_unknown_profile(tmp_path):
    _pdk_manifest(tmp_path / "pdk.toml", {"sg13g2_pr/nmos.sym": ("pdk/nmos.sym", b"nmos")})
    case = tmp_path / "case.toml"
    _case(case, profile="pdk.toml#missing")
    with pytest.raises(ValueError, match="Unknown support profile"):
        resolve_source_files(case)


def test_resolve_requires_own_source_files(tmp_path):
    case = tmp_path / "case.toml"
    _case(case, files=False)
    with pytest.raises(ValueError, match="nonempty list"):
        resolve_source_files(case)
