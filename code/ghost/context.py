"""Per-case working context shared by the linking steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .settings import LinkSettings
from .store import Row, Store
from .timing import TimingModel


@dataclass(frozen=True)
class CaseContext:
    """Everything the linking steps of one request need to read (nothing here is modified)."""

    case: Row
    user: str
    subject: dict[str, Any]
    store: Store
    settings: LinkSettings
    claims: Mapping[str, set[str]] | None
    timing: TimingModel

    @property
    def audit_at(self) -> str:
        """Audit timestamp of the request."""
        return self.case["audit_at"]

    def claimed_other(self, rid: str) -> bool:
        """True when another user's exact identifiers already claim this resource."""
        if not self.claims:
            return False
        return bool(self.claims.get(rid, set()) - {self.user})

    def claimed_only_by_user(self, rid: str) -> bool:
        """True when this user is the only claimant of the resource."""
        if not self.claims:
            return False
        return self.claims.get(rid, set()) == {self.user}
