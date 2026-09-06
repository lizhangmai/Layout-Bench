"""Trusted container helper: read one bounded regular file without following links."""

import os
import stat
import sys


def snapshot(root, path, limit):
    parts = path.split("/")
    if any(p in {"", ".", ".."} for p in parts) or path.startswith("/"):
        raise ValueError("Submission path must stay inside the workspace")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Submission must be a regular file without links")
            if before.st_size > limit:
                raise ValueError("Submission exceeds the task size limit")
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(content) > limit:
                raise ValueError("Submission exceeds the task size limit")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Submission changed while being copied; retry after closing the writer")
            return content
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(snapshot("/workspace", sys.argv[1], int(sys.argv[2])))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
