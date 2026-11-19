"""Facade of the linking stage: identity linking, state conclusion and the learned timing tables.

The implementation lives in settings, store, linking, anchoring, claims, conclusion and timing; this module keeps
`from ghost import linker` working for scripts that use the stage as a whole.
"""

from __future__ import annotations

from .claims import strong_claims
from .conclusion import all_conclusions, conclude, covering_files
from .linking import LinkResult, direct_links, file_ok, link_case, rec_ok
from .settings import DEL_EVENTS, LINK_SCORES, NONCOMPLIANT, ROLE_FACTOR, STATUS_RESULTS, STRONG, LinkSettings
from .store import Store
from .timing import TimingModel, learn_anon_phase, learn_phase, learn_timing, phase_pick, worker_time

__all__ = [
    "DEL_EVENTS",
    "LINK_SCORES",
    "NONCOMPLIANT",
    "ROLE_FACTOR",
    "STATUS_RESULTS",
    "STRONG",
    "LinkResult",
    "LinkSettings",
    "Store",
    "TimingModel",
    "all_conclusions",
    "conclude",
    "covering_files",
    "direct_links",
    "file_ok",
    "learn_anon_phase",
    "learn_phase",
    "learn_timing",
    "link_case",
    "phase_pick",
    "rec_ok",
    "strong_claims",
    "worker_time",
]
