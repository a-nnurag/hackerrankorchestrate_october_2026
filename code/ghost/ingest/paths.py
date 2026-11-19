"""Filesystem locations used by ingestion (dataset, observation cache, manual transcriptions)."""

from __future__ import annotations

import os

GHOST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(GHOST_DIR))

# GHOST_DATASET relocates the participant-facing dataset; GHOST_CACHE_DIR relocates observations.db.
DS = os.environ.get("GHOST_DATASET", os.path.join(REPO, "dataset"))
DB = os.path.join(os.environ.get("GHOST_CACHE_DIR", os.path.join(REPO, "code", ".cache")), "observations.db")

# Hand-made transcriptions of the image/PDF evidence (machines cannot read those files as text).
MANUAL_DIR = os.path.join(GHOST_DIR, "manual")
