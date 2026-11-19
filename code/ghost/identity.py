"""Identity resolution: map an email to a user and list the identifiers that were valid at audit_at."""

from __future__ import annotations

import collections
import csv
import os
from collections.abc import Callable
from typing import Any

from .ingest import DS, digits, norm_email, sha

Row = dict[str, str]

# How each audited profile field is normalised before comparison (phone numbers are compared as digits).
_NORMALISERS: dict[str, Callable[[str], str]] = {"email": norm_email, "email_hash": str.lower}


def _normaliser(field: str) -> Callable[[str], str]:
    return _NORMALISERS.get(field, digits)


def _read_rows(name: str) -> list[Row]:
    with open(os.path.join(DS, name), encoding="utf8") as f:
        return list(csv.DictReader(f))


class Identity:
    """Users, their identifier history and the lookups the linker needs."""

    def __init__(self) -> None:
        self.users: dict[str, Row] = {r["user_id"]: r for r in _read_rows("user_identities.csv")}
        self.audit: dict[str, list[Row]] = collections.defaultdict(list)
        for r in _read_rows("user_audit_log.csv"):
            self.audit[r["user_id"]].append(r)
        for events in self.audit.values():
            events.sort(key=lambda r: r["event_time"])
        # global maps identifier (at any time) -> users
        self.email_any: dict[str, set[str]] = collections.defaultdict(set)
        self.hash_any: dict[str, set[str]] = collections.defaultdict(set)
        self.phone_any: dict[str, set[str]] = collections.defaultdict(set)
        self._index_current_values()
        self._index_historical_values()
        self.hash_mismatch = sum(1 for r in self.users.values() if sha(r["email"]) != r["email_hash"].lower())

    def _index_current_values(self) -> None:
        for user, r in self.users.items():
            self.email_any[norm_email(r["email"])].add(user)
            self.hash_any[r["email_hash"].lower()].add(user)
            self.phone_any[digits(r["phone"])].add(user)

    def _index_historical_values(self) -> None:
        index = {"email": self.email_any, "email_hash": self.hash_any, "phone": self.phone_any}
        for user, events in self.audit.items():
            for e in events:
                if e["field_name"] in index:
                    for value in (e["old_value"], e["new_value"]):
                        index[e["field_name"]][_normaliser(e["field_name"])(value)].add(user)

    def _values_at(self, user: str, audit_at: str) -> tuple[dict[str, str], dict[str, set[str]]]:
        """(current values rolled back to audit_at, every older value seen up to audit_at) per audited field."""
        r = self.users[user]
        cur = {"email": norm_email(r["email"]), "email_hash": r["email_hash"].lower(), "phone": digits(r["phone"])}
        hist: dict[str, set[str]] = {"email": set(), "email_hash": set(), "phone": set()}
        events = self.audit.get(user, [])
        for e in reversed(events):
            if e["event_time"] > audit_at:  # undo changes made after audit_at
                cur[e["field_name"]] = _normaliser(e["field_name"])(e["old_value"])
        for e in events:
            if e["event_time"] <= audit_at:
                norm = _normaliser(e["field_name"])
                hist[e["field_name"]].add(norm(e["old_value"]))
                hist[e["field_name"]].add(norm(e["new_value"]))
        return cur, hist

    def asof(self, user: str, audit_at: str) -> dict[str, Any]:
        """Identifier sets valid at audit_at: current values (reverting later changes) plus all older values."""
        cur, hist = self._values_at(user, audit_at)
        emails_cur = {cur["email"]}
        emails_hist = hist["email"] - emails_cur
        hashes = {cur["email_hash"]} | hist["email_hash"] | {sha(e) for e in emails_cur | emails_hist}
        phones = {cur["phone"]} | hist["phone"]
        return {
            "user": user,
            "name": self.users[user]["name"].strip().lower(),
            "emails_cur": emails_cur,
            "emails_hist": emails_hist,
            "hashes": hashes,
            "phones": phones,
        }

    def resolve(self, email: str, audit_at: str) -> list[str]:
        """Users that ever had this email (or whose email hashes to it); `audit_at` is accepted for symmetry."""
        e = norm_email(email)
        users = set(self.email_any.get(e, ()))
        if not users:
            users = set(self.hash_any.get(sha(e), ()))
        return sorted(users)
