"""Feature switches for the hosted connector's dark tools (clinical trials):
whether to list a feature's tools to someone at all (`entitled`), and the
per-lab check each of those tools makes (`team_for`).

Both read with the service role: the switch tables are closed to connector
tokens, like everything the database gate doesn't open.
"""

from __future__ import annotations

import threading
import time

from api.supa import service_client

from . import lab

_enabled_cache: dict[str, tuple[float, frozenset[str]]] = {}
_cache_lock = threading.Lock()
_ENABLED_FOR = 60.0  # seconds; a switch turned on shows within a minute
_ENABLED_MAX = 5_000  # people; past it, old answers are dropped


def _enabled(user_id: str) -> frozenset[str]:
    """Every feature on for this person in any of their labs (for them, or for
    a lab they belong to): one lookup serves all the switches."""
    with _cache_lock:
        hit = _enabled_cache.get(user_id)
        if hit and time.monotonic() - hit[0] < _ENABLED_FOR:
            return hit[1]
    svc = service_client()
    mine = svc.table("user_features").select("feature").eq("user_id", user_id).execute().data
    on = {r["feature"] for r in mine or []}
    teams = [
        r["team_id"]
        for r in svc.table("team_members").select("team_id").eq("user_id", user_id).execute().data
        or []
    ]
    if teams:
        rows = svc.table("team_features").select("feature").in_("team_id", teams).execute().data
        on |= {r["feature"] for r in rows or []}
    answer = frozenset(on)
    with _cache_lock:
        if len(_enabled_cache) >= _ENABLED_MAX:
            now = time.monotonic()
            for k in [k for k, (t, _) in _enabled_cache.items() if now - t >= _ENABLED_FOR]:
                del _enabled_cache[k]
            if len(_enabled_cache) >= _ENABLED_MAX:
                _enabled_cache.clear()
        _enabled_cache[user_id] = (time.monotonic(), answer)
    return answer


def entitled(user_id: str | None, feature: str) -> bool:
    """Whether ``feature`` is on for this person in any of their labs. Decides
    whether its tools are listed."""
    return bool(user_id) and feature in _enabled(user_id)


def check(team: dict, feature: str, refusal: str) -> None:
    """``feature``'s switch, for this person in this (resolved) lab; raises
    ``LabError(refusal)`` when it is off."""
    svc = service_client()
    lab_on = (
        svc.table("team_features")
        .select("team_id")
        .eq("team_id", team["id"])
        .eq("feature", feature)
    )
    if lab_on.execute().data:
        return
    me = svc.table("user_features").select("user_id").eq("user_id", lab.current_user_id())
    if not me.eq("feature", feature).execute().data:
        raise lab.LabError(refusal)


def team_for(team_id: str | None, feature: str, refusal: str) -> dict:
    """The lab to act on: resolved as the caller (member, Claude access on;
    this also attributes the call for the audit log), then ``feature``'s switch."""
    team = lab.resolve_team(team_id)
    check(team, feature, refusal)
    return team
