"""Expose the selected process-local store and its request records.

This prototype adapter intentionally provides no persistence across restarts or
sharing across backend instances."""

from backend.infrastructure.persistence.memory import (
    InMemoryStore,
    RequestRecord,
    RequestConflict,
)

__all__: list[str] = ["InMemoryStore", "RequestRecord", "RequestConflict"]
