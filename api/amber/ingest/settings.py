"""Indexing settings an admin can change at runtime (Admin > Settings). Stored in the `settings` table."""

from dataclasses import asdict, dataclass
from typing import Any

from amber import repository
from amber.util.db import Connection

KEY = "indexing"


@dataclass(frozen=True)
class IndexingSettings:
    chunk_size_tokens: int = 800
    chunk_overlap_pct: int = 15
    max_upload_mb: int = 50

    @property
    def chunk_overlap_tokens(self) -> int:
        return self.chunk_size_tokens * self.chunk_overlap_pct // 100

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


# (min, max) allowed for each field; the Admin form uses the same ranges.
LIMITS: dict[str, tuple[int, int]] = {
    "chunk_size_tokens": (200, 2000),
    "chunk_overlap_pct": (0, 50),
    "max_upload_mb": (1, 200),
}


def validate(values: dict[str, Any]) -> IndexingSettings:
    """Raises ValueError naming the first field that is out of range."""
    for name, (low, high) in LIMITS.items():
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return IndexingSettings(**{name: values[name] for name in LIMITS})


def load(conn: Connection) -> IndexingSettings:
    """The saved settings, with defaults for anything missing or no longer valid."""
    row = repository.get_setting(conn, KEY)
    if row is None:
        return IndexingSettings()
    try:
        return validate({**asdict(IndexingSettings()), **row["value"]})
    except (ValueError, TypeError):
        return IndexingSettings()


def save(conn: Connection, settings: IndexingSettings, updated_by: Any) -> None:
    repository.set_setting(conn, KEY, asdict(settings), updated_by)
