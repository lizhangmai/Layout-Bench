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
from .harnesses import PROCESS_FEEDBACK_CAPABILITY
from .inference import INFERENCE_SOCKET, LEGACY_INFERENCE_SOCKET
from .recorder import RecordingError
from .recording import SessionResult

MAX_CONSOLE_BYTES = 64 * 1024 * 1024
MAX_PROCESS_FEEDBACK = 16
PDK_RESOURCE_KIND = "reviewed-pdk-view"
PDK_RESOURCE_FILES = (
    "ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/__init__.py",
    "ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python/cni/box.py",
    "ihp-sg13g2/libs.tech/klayout/python/pypreprocessor/pypreprocessor/__init__.py",
)
PDK_RESOURCE_ENVIRONMENT = {
    "KLAYOUT": "1",
    "PYTHONPATH": ("/resources/ihp-sg13g2/libs.tech/klayout/python:"
                    "/resources/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python"),
}


def _resource_manifest(resources):
    manifest = resources.get("manifest.json")
    if manifest is None:
        return None
    if not isinstance(manifest, Asset):
        raise TypeError("Resource manifest must be an Asset")
    try:
        value = json.loads(manifest.content)
    except (TypeError, ValueError) as error:
        raise ValueError("Resource manifest is not valid JSON") from error
    if not isinstance(value, dict):
        raise TypeError("Resource manifest must be a JSON object")
    return value


def resource_environment(resources):
    """Return the safe, container-local environment for a reviewed PDK bundle.

    The bundle is content-addressed before it reaches this function.  The
    provenance marker lets ordinary support bundles remain unchanged, while
    the file markers also support callers that already loaded a Bundle and
    passed only its ``files`` mapping.  No task or reference material is
    inferred or added here.
    """
    manifest = _resource_manifest(resources)
    provenance = manifest.get("provenance", {}) if manifest else {}
    if not isinstance(provenance, dict):
        raise TypeError("Resource manifest provenance must be an object")
    pdk = provenance.get("kind") == PDK_RESOURCE_KIND or any(
        name in resources for name in PDK_RESOURCE_FILES
    )
    if not pdk:
        return {}
    missing = [name for name in PDK_RESOURCE_FILES if name not in resources]
    if missing:
        message = ("PDK resource bundle is incomplete; missing " + ", ".join(missing) +
                   ". Recreate it with `public_preview.py prepare --output <new-dir>`.")
        raise ValueError(message)
    return dict(PDK_RESOURCE_ENVIRONMENT)


def resource_preflight(resources):
    """Describe mounted resource checks without exposing task/reference files."""
    environment = resource_environment(resources)
    result = {"schema_version": 1, "mount": "/resources", "environment": environment,
              "bundles": [], "python_imports": []}
    if environment:
        manifest = _resource_manifest(resources)
        provenance = manifest.get("provenance", {}) if manifest else {}
        result["bundles"].append({"kind": PDK_RESOURCE_KIND,
                                  "view_sha256": provenance.get("view_sha256")})
        result["python_imports"] = ["klayout", "pya", "sg13g2_pycell_lib"]
        result["command"] = ["python", "-c", "import klayout, pya, sg13g2_pycell_lib"]
    return result


def _agent_environment(config, resources):
    """Merge automatic resource paths with explicitly configured public values."""
    environment = dict(config.environment)
    pdk = resource_environment(resources)
    if not pdk:
        return environment
    if "KLAYOUT" in environment and environment["KLAYOUT"] != pdk["KLAYOUT"]:
        raise ValueError("A reviewed PDK resource bundle requires KLAYOUT=1")
    paths = pdk["PYTHONPATH"].split(":")
    paths.extend(value for value in environment.get("PYTHONPATH", "").split(":") if value)
    environment["PYTHONPATH"] = ":".join(dict.fromkeys(paths))
    environment.setdefault("KLAYOUT", pdk["KLAYOUT"])
    return environment


def task_message(task, config):
    message = ("Generate a GDS layout implementing the authoritative netlist and all task requirements.\n"
               "Read /protocol/task.json for input paths, top cell, output path and limits.\n"
               "Read /protocol/harness.json for the session protocol and declared capabilities.\n"
               "Read /protocol/resources.json for reviewed resource paths and the optional import preflight.\n"
               "Task inputs are read-only in /task; reviewed resources are in /resources.\n"
               "The writable /workspace starts empty. Available tools come from the recorded image.\n"
               f"Wall-clock budget: {config.wall_seconds:g} seconds, including your tool calls.\n"
               f"Write {task.description()['output']['path']}, then explicitly submit with:\n"
               "python -I /protocol/submit.py\n"
               "Wait for the host receipt. You may replace the submission before the deadline.\n"
               "Only the last accepted snapshot is evaluated; writing a file alone is not submission.\n"
               "The receipt confirms file delivery, not DRC/LVS or performance success.\n")
    if PROCESS_FEEDBACK_CAPABILITY in config.harness.capabilities:
        message += ("This harness declares optional same-semantic process feedback. For a read-only\n"
                     "check of the current output snapshot, run:\n"
                     "python -I /protocol/process_check.py\n"
                     "Feedback is diagnostic and never replaces the final independent evaluation.\n")
    return message


class DockerSession:
    """No provider credentials/network or evaluator materials enter this container."""

    def __init__(self, image):
        inspected = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", image], text=True, timeout=30))[0]
        if inspected["Config"].get("Volumes"):
            raise ValueError("Session images must not declare writable volumes outside the bounded workspace")
        self.image_id = inspected["Id"]

    def run(self, task, config, resources, message, *, inference=None, recorder=None, feedback=None):
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
        submissions, candidate, process_feedback = [], None, []
        termination, reason, code = "infrastructure_error", "", None
        started = None
        elapsed = 0.0
        agent_environment = _agent_environment(config, resources)
        resource_info = resource_preflight(resources)
        identity = {"image_id": self.image_id, "network": "none", "read_only_root": True,
                    "harness": config.harness.identity(),
                    "memory_mb": config.memory_mb, "cpus": config.cpus, "pids": config.pids,
                    "workspace_mb": config.workspace_mb, "tmp_mb": 64, "shm_mb": 16,
                    "user": f"{uid}:{gid}", "wall_seconds": config.wall_seconds,
                    "console_limit_bytes": console_limit,
                    "resource_environment": resource_info["environment"],
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
            protocol_files = {
                "task.json": Asset(json.dumps(task.description()).encode(), "json"),
                "prompt.txt": Asset(message.encode(), "text"),
                "harness.json": Asset(json.dumps(config.harness.identity(), sort_keys=True).encode(), "json"),
                "resources.json": Asset(json.dumps(resource_info, sort_keys=True).encode(), "json"),
                **{name: Asset(Path(__file__).with_name(name).read_bytes(), "python")
                   for name in ("snapshot.py", "submit.py")}}
            feedback_enabled = (feedback is not None
                                and PROCESS_FEEDBACK_CAPABILITY in config.harness.capabilities)
            if feedback_enabled:
                protocol_files["process_check.py"] = Asset(
                    Path(__file__).with_name("process_check.py").read_bytes(), "python")
            groups = {"agent": config.files, "resources": resources, "protocol": protocol_files}
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
            env = [arg for k, v in agent_environment.items() for arg in ("--env", f"{k}={v}")]
            # Agent-specific loader/locale settings must not affect the trusted reader.
            reader_env = [arg for k in agent_environment for arg in ("--env", f"{k}=")]
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

                def snapshot_candidate(remaining):
                    if remaining <= 0:
                        raise ValueError("Snapshot deadline has passed")
                    copied = subprocess.run(
                        ["docker", "exec", *reader_env,
                         "--env", "LD_PRELOAD=", "--env", "LD_LIBRARY_PATH=", "--env", "LD_AUDIT=",
                         cid, "/usr/bin/python3", "-I", "/protocol/snapshot.py",
                         task.output.path, str(task.output.max_bytes)], capture_output=True,
                        timeout=remaining, check=False)
                    if copied.returncode:
                        raise ValueError(copied.stderr.decode(errors="replace")[:1024])
                    if len(copied.stdout) > task.output.max_bytes:
                        raise ValueError("Snapshot exceeds the task size limit")
                    return Asset(copied.stdout, "gds")

                feedback_sequence = 0

                def process_check():
                    nonlocal feedback_sequence
                    feedback_sequence += 1
                    sequence = feedback_sequence
                    requested_at = time.monotonic()
                    record("process_feedback.request", sequence=sequence,
                           request={"action": "process_check"})
                    entry = {
                        "sequence": sequence, "accepted": False, "candidate": None,
                        "tool_identity": None, "elapsed_seconds": 0.0,
                        "outcome": "denied", "physical_valid": None, "specs_pass": None,
                        "task_success": None, "report": None, "report_path": None,
                        "error": None,
                    }
                    try:
                        if sequence > MAX_PROCESS_FEEDBACK:
                            entry["error"] = "feedback_budget_exhausted"
                            return {"accepted": False, "sequence": sequence,
                                    "feedback": entry}
                        remaining = deadline - requested_at
                        if remaining <= 0:
                            entry["error"] = "budget_exhausted"
                            return {"accepted": False, "sequence": sequence,
                                    "feedback": entry}
                        frozen = snapshot_candidate(remaining)
                        entry["candidate"] = (recorder.archive(frozen) if recorder
                                               else frozen.identity())
                        result = feedback(frozen, sequence)
                        if not isinstance(result, dict) or not isinstance(result.get("report"), dict):
                            raise TypeError("Process feedback callback must return a report")
                        evaluated = result["report"]
                        entry.update(
                            accepted=True,
                            outcome=evaluated.get("outcome", "error"),
                            physical_valid=evaluated.get("physical_valid"),
                            specs_pass=evaluated.get("specs_pass"),
                            task_success=evaluated.get("task_success"),
                            tool_identity=evaluated.get("backends"),
                            report=result.get("report_ref"),
                            report_path=result.get("report_path"),
                        )
                        if entry["report"] is not None and not isinstance(entry["report"], dict):
                            raise ValueError("Process feedback report reference is invalid")
                        if entry["report_path"] is not None:
                            entry["report_path"] = relative(entry["report_path"],
                                                             "process feedback report path")
                    except RecordingError:
                        raise
                    except Exception as error:  # noqa: BLE001 -- feedback failures are durable diagnostics
                        entry.update(accepted=True, outcome="error",
                                     error=f"{type(error).__name__}: {error}"[:1024])
                    finally:
                        entry["elapsed_seconds"] = time.monotonic() - requested_at
                        process_feedback.append(entry)
                        record("process_feedback.result", **entry)
                    return {"accepted": entry["accepted"], "sequence": sequence,
                            "feedback": entry}

                while process.poll() is None:
                    if recording_failed.is_set() or (recorder and recorder.error):
                        raise RecordingError("Session evidence is incomplete")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        termination = "budget_exhausted"
                        reason = "Wall-clock limit reached"
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
                            if len(request) > 1024:
                                raise ValueError("Control request is too large")
                            action = json.loads(request)
                            if action == {"action": "submit"}:
                                remaining = deadline - time.monotonic()
                                frozen = snapshot_candidate(remaining)
                                accepted_at = time.monotonic()
                                if accepted_at >= deadline:
                                    raise ValueError("Submission snapshot missed the deadline")
                                archived = recorder.archive(frozen) if recorder else None
                                receipt = {"accepted": True, "sequence": len(submissions) + 1,
                                           "elapsed_seconds": accepted_at - started, **frozen.identity()}
                                # The durable event commits acceptance before the client can see it.
                                record("submission", receipt=receipt, candidate=archived)
                                candidate = frozen
                                submissions.append(receipt)
                            elif action == {"action": "process_check"} and feedback_enabled:
                                receipt = process_check()
                            elif action == {"action": "process_check"}:
                                raise ValueError("Process feedback capability is not declared")
                            else:
                                raise ValueError("Expected a submit or process_check action")
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
                        reason = ("OOM killed" if state.get("OOMKilled") else
                                  f"Agent exited with code {code}" if code else "")
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
                             Asset(bytes(console), "text"), truncated, identity,
                             process_feedback)
