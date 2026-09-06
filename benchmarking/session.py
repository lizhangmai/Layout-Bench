"""Offline CLI execution with host-enforced resources and explicit GDS snapshots."""

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .files import Asset, relative
from .inference import INFERENCE_SOCKET, LEGACY_INFERENCE_SOCKET
from .recorder import RecordingError
from .recording import SessionResult

MAX_CONSOLE_BYTES = 64 * 1024 * 1024


def task_message(task, config):
    return ("Generate a GDS layout implementing the authoritative netlist and all task requirements.\n"
            "Read /protocol/task.json for input paths, top cell, output path and limits.\n"
            "Read /protocol/harness.json for the session protocol and declared capabilities.\n"
            "Task inputs are read-only in /task; reviewed resources are in /resources.\n"
            "The writable /workspace starts empty. Available tools come from the recorded image.\n"
            f"Wall-clock budget: {config.wall_seconds:g} seconds, including your tool calls.\n"
            f"Write {task.description()['output']['path']}, then explicitly submit with:\n"
            "python -I /protocol/submit.py\n"
            "Wait for the host receipt. You may replace the submission before the deadline.\n"
            "Only the last accepted snapshot is evaluated; writing a file alone is not submission.\n"
            "The receipt confirms file delivery, not DRC/LVS or performance success.\n")


class DockerSession:
    """No provider credentials/network or evaluator materials enter this container."""

    def __init__(self, image):
        inspected = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", image], text=True, timeout=30))[0]
        if inspected["Config"].get("Volumes"):
            raise ValueError("Session images must not declare writable volumes outside the bounded workspace")
        self.image_id = inspected["Id"]

    def run(self, task, config, resources, message, *, inference=None, recorder=None):
        if inference and recorder:
            inference.recorder = recorder
        console = bytearray()
        console_bytes = 0
        console_limit = MAX_CONSOLE_BYTES
        recording_failed = threading.Event()
        uid, gid = (os.getuid(), os.getgid()) if os.getuid() else (1000, 1000)

        def record(kind, **data):
            if recorder:
                recorder.event(kind, **data)
        truncated = False
        submissions, candidate = [], None
        termination, reason, code = "infrastructure_error", "", None
        started = None
        elapsed = 0.0
        identity = {"image_id": self.image_id, "network": "none", "read_only_root": True,
                    "harness": config.harness.identity(),
                    "memory_mb": config.memory_mb, "cpus": config.cpus, "pids": config.pids,
                    "workspace_mb": config.workspace_mb, "tmp_mb": 64, "shm_mb": 16,
                    "user": f"{uid}:{gid}", "wall_seconds": config.wall_seconds,
                    "console_limit_bytes": console_limit,
                    "source_sha256": Asset(Path(__file__).read_bytes(), "python").sha256}

        def drain(stream):
            nonlocal truncated, console_bytes
            try:
                while chunk := stream.read1(8192):
                    if recording_failed.is_set():
                        continue  # Drain the pipe until container removal closes Docker attach.
                    available = max(0, 65536 - len(console))
                    console.extend(chunk[:available])
                    truncated |= len(chunk) > available
                    try:
                        if console_bytes + len(chunk) > console_limit:
                            record("console.limit", bytes_recorded=console_bytes)
                            recording_failed.set()
                            continue
                        if recorder:
                            record("console.chunk", offset=console_bytes,
                                   content=recorder.archive(Asset(chunk, "binary")))
                        console_bytes += len(chunk)
                    except OSError:
                        recording_failed.set()
            except OSError:
                recording_failed.set()

        with tempfile.TemporaryDirectory(prefix="lb-session-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            task.materialize(root / "task")
            groups = {"agent": config.files, "resources": resources, "protocol": {
                "task.json": Asset(json.dumps(task.description()).encode(), "json"),
                "prompt.txt": Asset(message.encode(), "text"),
                "harness.json": Asset(json.dumps(config.harness.identity(), sort_keys=True).encode(), "json"),
                **{name: Asset(Path(__file__).with_name(name).read_bytes(), "python")
                   for name in ("snapshot.py", "submit.py")}}}
            if inference:
                profile = Asset(json.dumps(inference.public, sort_keys=True).encode(), "json")
                groups["protocol"]["inference.json"] = profile
                # Keep the old filename readable while harnesses migrate to the
                # generic inference profile name.
                groups["protocol"]["model.json"] = profile
            for group, files in groups.items():
                (root / group).mkdir()
                for name, asset in files.items():
                    destination = root / group / relative(name, "session input")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(asset.content)
                    destination.chmod(0o444)
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(root / "protocol/control.sock"))
            if os.getuid() == 0:
                os.chown(root / "protocol/control.sock", uid, -1)
            (root / "protocol/control.sock").chmod(0o600)
            server.listen(4)
            server.settimeout(0.05)
            if inference:
                # Keep the former model.sock path as a compatibility alias while
                # new harnesses use the provider-neutral inference.sock name.
                legacy_socket = root / LEGACY_INFERENCE_SOCKET.lstrip("/")
                legacy_socket.symlink_to(Path(INFERENCE_SOCKET).name)
            mounts = [arg for name in ("task", "agent", "resources", "protocol")
                      for arg in ("--mount", f"type=bind,src={root/name},dst=/{name},readonly")]
            env = [arg for k, v in config.environment.items() for arg in ("--env", f"{k}={v}")]
            # Agent-specific loader/locale settings must not affect the trusted reader.
            reader_env = [arg for k in config.environment for arg in ("--env", f"{k}=")]
            cid, process, reader = None, None, None
            try:
                cid = subprocess.check_output([
                    "docker", "create", "--network", "none", "--read-only", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--user", f"{uid}:{gid}", "--workdir", "/workspace",
                    "--memory", f"{config.memory_mb}m", "--memory-swap", f"{config.memory_mb}m",
                    "--cpus", str(config.cpus), "--pids-limit", str(config.pids), "--shm-size", "16m",
                    "--tmpfs", f"/workspace:rw,nosuid,nodev,size={config.workspace_mb}m,uid={uid},gid={gid},mode=700",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777", "--log-driver", "none",
                    "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
                    *env, *mounts, "--entrypoint", config.command[0], self.image_id, *config.command[1:],
                ], text=True, stderr=subprocess.PIPE, timeout=30).strip()
                record("session.created", container_id=cid, environment=identity)
                started = time.monotonic()
                deadline = started + config.wall_seconds
                if inference:
                    inference.start(root / INFERENCE_SOCKET.lstrip("/"), deadline, uid=uid)
                process = subprocess.Popen(["docker", "start", "-a", cid], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                reader = threading.Thread(target=drain, args=(process.stdout,), daemon=True)
                reader.start()
                while process.poll() is None:
                    if recording_failed.is_set() or (recorder and recorder.error):
                        raise RecordingError("Session evidence is incomplete")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        termination = "budget_exhausted"
                        break
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        continue
                    with connection:
                        connection.settimeout(max(.001, min(1, deadline - time.monotonic())))
                        receipt = {"accepted": False, "reason": "Invalid submission request"}
                        try:
                            request = connection.makefile("rb").readline(1025)
                            if len(request) > 1024 or json.loads(request) != {"action": "submit"}:
                                raise ValueError("Expected a submit action")
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise ValueError("Submission deadline has passed")
                            copied = subprocess.run(
                                ["docker", "exec", *reader_env,
                                 "--env", "LD_PRELOAD=", "--env", "LD_LIBRARY_PATH=", "--env", "LD_AUDIT=",
                                 cid, "/usr/bin/python3", "-I", "/protocol/snapshot.py",
                                 task.output.path, str(task.output.max_bytes)], capture_output=True,
                                timeout=remaining, check=False)
                            if copied.returncode:
                                raise ValueError(copied.stderr.decode(errors="replace")[:1024])
                            if len(copied.stdout) > task.output.max_bytes:
                                raise ValueError("Submission exceeds the task size limit")
                            frozen = Asset(copied.stdout, "gds")
                            archived = recorder.archive(frozen) if recorder else None
                            accepted_at = time.monotonic()
                            if accepted_at >= deadline:
                                raise ValueError("Submission snapshot missed the deadline")
                            receipt = {"accepted": True, "sequence": len(submissions) + 1,
                                       "elapsed_seconds": accepted_at - started, **frozen.identity()}
                            # The durable event commits acceptance before the client can see it.
                            record("submission", receipt=receipt, candidate=archived)
                            candidate = frozen
                        except RecordingError:
                            raise
                        except (OSError, ValueError, subprocess.SubprocessError) as error:
                            receipt = {"accepted": False, "reason": str(error)[:1024],
                                       "elapsed_seconds": time.monotonic() - started}
                            record("submission", receipt=receipt, candidate=None)
                        submissions.append(receipt)
                        try:
                            connection.sendall(json.dumps(receipt).encode() + b"\n")
                        except OSError:
                            pass  # The host event is authoritative even if the client disconnects.
                if termination != "budget_exhausted":
                    state = json.loads(subprocess.check_output(
                        ["docker", "inspect", "--format", "{{json .State}}", cid], text=True, timeout=10))
                    code = state["ExitCode"]
                    if state.get("Error") or (process.returncode and code == 0):
                        reason = state.get("Error") or "Docker attach failed"
                    else:
                        termination = "completed" if code == 0 else "agent_error"
                        reason = "OOM killed" if state.get("OOMKilled") else ""
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                termination, reason = "infrastructure_error", str(error)
            finally:
                elapsed = time.monotonic() - started if started else 0.0
                server.close()
                if inference:
                    inference.stop()
                if cid:
                    cleanup = subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=30, check=False)
                    if cleanup.returncode:
                        termination, reason = "infrastructure_error", "Session container cleanup failed"
                if process:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        termination, reason = "infrastructure_error", "Docker attach cleanup timed out"
                if reader:
                    reader.join(timeout=10)
                    if reader.is_alive():
                        recording_failed.set()
                if recording_failed.is_set() or (recorder and recorder.error):
                    termination, reason = "infrastructure_error", "Session evidence is incomplete"
                # TemporaryDirectory cleanup must be able to unlink staged files.
                for path in root.rglob("*"):
                    if path.is_dir():
                        path.chmod(0o755)
        record("session.stopped", termination=termination, reason=reason, elapsed_seconds=elapsed,
               exit_code=code, console_bytes=console_bytes,
               console_complete=not recording_failed.is_set())
        return SessionResult(termination, reason, elapsed, code, submissions, candidate,
                             Asset(bytes(console), "text"), truncated, identity)
