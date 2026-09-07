"""Private, durable run evidence. A submission event is the acceptance commit."""

import errno
import fcntl
import json
import os
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .files import Asset, read_file


class RecordingError(OSError):
    """Evidence could not be persisted; this run cannot produce a score."""


class BatchLeaseError(OSError):
    """Another process currently owns the exclusive lease for a batch."""


class BatchLease:
    """Coordinate local recovery owners without changing batch evidence."""

    filename = ".batch.lock"

    def __init__(self, destination):
        self.root = Path(destination).absolute()
        self.path = self.root / self.filename
        self._stream = None

    def __enter__(self):
        if self._stream is not None:
            raise BatchLeaseError(errno.EBUSY, f"Batch is already leased: {self.root}")
        stream = self.path.open("a+b")
        try:
            os.fchmod(stream.fileno(), 0o600)
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise BatchLeaseError(errno.EWOULDBLOCK,
                                       f"Batch is already leased: {self.root}") from error
            raise
        self._stream = stream
        return self

    def __exit__(self, exception_type, exception, traceback):
        stream, self._stream = self._stream, None
        if stream is None:
            return False
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
        return False


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, content, mode=0o600):
    """Publish only a complete file, then persist its directory entry."""
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class RunRecorder:
    def __init__(self, destination):
        self.root = Path(destination).absolute()
        self.root.mkdir(parents=True, mode=0o700)
        sync_directory(self.root.parent)
        (self.root / "artifacts").mkdir(mode=0o700)
        atomic_write(self.root / "events.jsonl", b"")
        self._lock = threading.RLock()
        self._sequence = 0
        self._started = time.monotonic()
        self.error = None
        self._closed = False

    @classmethod
    def resume(cls, destination):
        """Reopen an unfinished evidence directory without replacing its journal."""
        self = cls.__new__(cls)
        self.root = Path(destination).absolute()
        if not self.root.is_dir() or not (self.root / "artifacts").is_dir():
            raise FileNotFoundError(self.root)
        self._lock = threading.RLock()
        self._sequence = 0
        with (self.root / "events.jsonl").open("rb") as stream:
            for line in stream:
                if not line.endswith(b"\n"):
                    raise ValueError("Cannot resume an event journal with an incomplete tail")
                event = json.loads(line)
                self._sequence += 1
                if (event.get("schema_version") != 1
                        or event.get("sequence") != self._sequence):
                    raise ValueError("Cannot resume an invalid event journal")
        self._started = time.monotonic()
        self.error = None
        self._closed = False
        return self

    def _write(self, operation):
        if self._closed:
            raise RecordingError("Run recorder is closed")
        if self.error:
            raise RecordingError(self.error)
        try:
            return operation()
        except OSError as error:
            self.error = "Run evidence persistence failed"
            raise RecordingError(self.error) from error

    def archive(self, asset):
        with self._lock:
            path = self.root / "artifacts" / asset.sha256
            if not path.exists():
                self._write(lambda: atomic_write(path, asset.content, 0o400))
            return {**asset.identity(), "path": f"artifacts/{asset.sha256}"}

    def save(self, report, *, filename="run.json"):
        if filename not in {"run.json", "batch.json"}:
            raise ValueError("Unsupported record filename")
        with self._lock:
            content = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
            self._write(lambda: atomic_write(self.root / filename, content))

    def event(self, kind, **data):
        with self._lock:
            event = {"schema_version": 1, "sequence": self._sequence + 1,
                     "time": datetime.now(UTC).isoformat(),
                     "elapsed_seconds": time.monotonic() - self._started,
                     "kind": kind, "data": data}
            content = (json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n").encode()

            def append():
                with (self.root / "events.jsonl").open("ab") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())

            self._write(append)
            self._sequence += 1
            return event


    def finish(self, report, *, filename="run.json", kind="run.finished"):
        """Seal the journal and bind its exact bytes to the final atomic report."""
        with self._lock:
            self.event(kind, termination=report["termination"], outcome=report["outcome"])
            report["events"].update(Asset((self.root / "events.jsonl").read_bytes(), "jsonl").identity())
            report["phase"] = "finished"
            self.save(report, filename=filename)
            self._closed = True


def recover_submissions(destination):
    """Read committed submissions, tolerating only an unfinished final journal line.

    Does not resume an agent, modify the old run, or turn an interrupted run into
    a score. Orphaned blobs without an acceptance event are never submissions.
    """
    root = Path(destination).absolute()
    submissions, candidate = [], None
    count = 0
    truncated = False
    with (root / "events.jsonl").open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                truncated = True
                break
            event = json.loads(line)
            count += 1
            if event.get("schema_version") != 1 or event.get("sequence") != count:
                raise ValueError("Invalid event journal sequence or schema")
            if event["kind"] != "submission":
                continue
            receipt = event["data"]["receipt"]
            if receipt["accepted"]:
                ref = event["data"]["candidate"]
                if ref["path"] != f'artifacts/{ref["sha256"]}' or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
                    raise ValueError("Invalid candidate artifact path")
                asset = Asset(read_file(root, ref["path"]), "gds")
                if ref != {**asset.identity(), "path": ref["path"]} or any(
                        receipt[k] != v for k, v in asset.identity().items()):
                    raise ValueError("Committed candidate integrity mismatch")
                candidate = ref
            submissions.append(receipt)
    return {"submissions": submissions, "candidate": candidate,
            "journal_events": count, "incomplete_tail": truncated}
