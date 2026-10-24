"""Feature switches for the hosted connector's dark tools (clinical trials,
saved searches): whether to list a feature's tools to someone at all
(`entitled`), and the per-lab check each of those tools makes (`check`).

Both read with the service role: the switch tables are closed to connector
tokens, like everything the database gate doesn't open.
"""

from __future__ import annotations

import time

from api.supa import service_client

from . import lab

_entitled_cache: dict[tuple[str, str], tuple[float, bool]] = {}
_ENTITLED_FOR = 60.0  # seconds; a switch turned on shows within a minute
_ENTITLED_MAX = 5_000  # answers; past it, old ones are dropped


def entitled(user_id: str | None, feature: str) -> bool:
    """Whether ``feature`` is on for this person in any of their labs (for them,
    or for a lab they belong to). Decides whether its tools are listed."""
    if not user_id:
        return False
    key = (feature, user_id)
    hit = _entitled_cache.get(key)
    if hit and time.monotonic() - hit[0] < _ENTITLED_FOR:
        return hit[1]
    svc = service_client()
    mine = (
        svc.table("user_features").select("feature").eq("user_id", user_id).eq("feature", feature)
    )
    ok = bool(mine.execute().data)
    if not ok:
        teams = [
            r["team_id"]
            for r in svc.table("team_members")
            .select("team_id")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        ]
        if teams:
            on = (
                svc.table("team_features")
                .select("team_id")
                .eq("feature", feature)
                .in_("team_id", teams)
            )
            ok = bool(on.execute().data)
    if len(_entitled_cache) >= _ENTITLED_MAX:
        now = time.monotonic()
        for k in [k for k, (t, _) in _entitled_cache.items() if now - t >= _ENTITLED_FOR]:
            del _entitled_cache[k]
        if len(_entitled_cache) >= _ENTITLED_MAX:
            _entitled_cache.clear()
    _entitled_cache[key] = (time.monotonic(), ok)
    return ok


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
