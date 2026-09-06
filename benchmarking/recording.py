"""Session result, separating why execution stopped from the frozen submission."""

from dataclasses import dataclass

from .files import Asset


@dataclass
class SessionResult:
    termination: str
    reason: str
    elapsed_seconds: float
    exit_code: int | None
    submissions: list[dict]
    candidate: Asset | None
    console: Asset
    console_truncated: bool
    environment: dict
