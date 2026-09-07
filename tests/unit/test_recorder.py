"""Durable acceptance, journal recovery and persistence failure boundaries."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from benchmarking.files import Asset
from benchmarking.recorder import (
    BatchLease,
    BatchLeaseError,
    RecordingError,
    RunRecorder,
    recover_submissions,
)

pytestmark = [pytest.mark.unit, pytest.mark.acceptance, pytest.mark.acceptance_fast]


def test_process_exit_keeps_committed_submission_but_not_orphan(tmp_path):
    root = tmp_path / "run"
    code = '''
import os, sys
from benchmarking.files import Asset
from benchmarking.recorder import RunRecorder
r = RunRecorder(sys.argv[1])
a = Asset(b"accepted", "gds")
ref = r.archive(a)
r.event("submission", receipt={"accepted": True, "sequence": 1, **a.identity()}, candidate=ref)
r.archive(Asset(b"not committed", "gds"))
os._exit(91)
'''
    process = subprocess.run([sys.executable, "-c", code, str(root)], check=False)
    assert process.returncode == 91
    before = (root / "events.jsonl").read_bytes()
    result = recover_submissions(root)
    assert (root / result["candidate"]["path"]).read_bytes() == b"accepted"
    assert len(result["submissions"]) == 1
    with (root / "events.jsonl").open("ab") as stream:
        stream.write(b'{"unfinished":')
    assert recover_submissions(root)["incomplete_tail"]
    assert (root / "events.jsonl").read_bytes() == before + b'{"unfinished":'
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "events.jsonl").stat().st_mode & 0o777 == 0o600


def test_recovery_keeps_the_last_snapshot_after_duplicate_submissions(tmp_path):
    recorder = RunRecorder(tmp_path / "run")
    first = Asset(b"first", "gds")
    last = Asset(b"last", "gds")
    first_ref = recorder.archive(first)
    last_ref = recorder.archive(last)
    for sequence, reference, candidate in ((1, first_ref, first), (2, last_ref, last), (3, last_ref, last)):
        recorder.event("submission", receipt={"accepted": True, "sequence": sequence, **candidate.identity()},
                       candidate=reference)

    recovered = recover_submissions(recorder.root)

    assert [receipt["sequence"] for receipt in recovered["submissions"]] == [1, 2, 3]
    assert recovered["candidate"] == last_ref


def test_write_failure_poisoning_preserves_previous_report(tmp_path, monkeypatch):
    recorder = RunRecorder(tmp_path / "run")
    recorder.save({"phase": "running"})
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(RecordingError):
            recorder.save({"phase": "finished"})
    assert json.loads((recorder.root / "run.json").read_text())["phase"] == "running"
    with pytest.raises(RecordingError):
        recorder.event("submission", receipt={"accepted": True})
    assert recover_submissions(recorder.root)["candidate"] is None


def test_corruption_and_concurrent_event_order(tmp_path):
    recorder = RunRecorder(tmp_path / "run")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: recorder.event("test", n=n), range(40)))
    assert recover_submissions(recorder.root)["journal_events"] == 40
    a = Asset(b"original", "gds")
    ref = recorder.archive(a)
    recorder.event("submission", receipt={"accepted": True, **a.identity()}, candidate=ref)
    path = recorder.root / ref["path"]
    path.chmod(0o600)
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        recover_submissions(recorder.root)


def test_finished_report_binds_a_sealed_journal(tmp_path):
    recorder = RunRecorder(tmp_path / "run")
    report = {"termination": "completed", "outcome": "no_submission", "events": {"path": "events.jsonl"}}
    recorder.finish(report)
    journal = (recorder.root / "events.jsonl").read_bytes()
    assert report["events"]["sha256"] == Asset(journal, "jsonl").sha256
    with pytest.raises(RecordingError, match="closed"):
        recorder.event("late.worker")
    assert (recorder.root / "events.jsonl").read_bytes() == journal


def test_batch_lease_allows_one_recovery_owner_at_a_time(tmp_path):
    root = tmp_path / "run"
    RunRecorder(root)
    with BatchLease(root), pytest.raises(BatchLeaseError, match="already leased"), BatchLease(root):
        pass
    with BatchLease(root):
        pass


def test_batch_lease_is_exclusive_across_processes(tmp_path):
    root = tmp_path / "run"
    RunRecorder(root)
    holder = subprocess.Popen(
        [sys.executable, "-c", """
from benchmarking.recorder import BatchLease
import sys
with BatchLease(sys.argv[1]):
    print('ready', flush=True)
    sys.stdin.read()
""", str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        attempt = subprocess.run(
            [sys.executable, "-c", """
from benchmarking.recorder import BatchLease
import sys
try:
    with BatchLease(sys.argv[1]):
        print('acquired')
except OSError as error:
    print(error)
    raise SystemExit(3)
""", str(root)], capture_output=True, text=True, check=False)
        assert attempt.returncode == 3
        assert "already leased" in attempt.stdout
    finally:
        holder.stdin.close()
        assert holder.wait(timeout=5) == 0
