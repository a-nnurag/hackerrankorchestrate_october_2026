"""`python -m ghost.ingest`: build the observation database and print its statistics."""

from __future__ import annotations

from . import build

if __name__ == "__main__":
    print(build())
