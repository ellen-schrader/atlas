"""Switch a feature on or off for a person or a lab (service role).

For the local stack. In prod a switch goes in a migration, so it reaches the
database through the normal merge-to-main deploy.

    python -m api.features on  clinical_trials --user ada@lab.test
    python -m api.features on  clinical_trials --team ali-lab
    python -m api.features off clinical_trials --user ada@lab.test
    python -m api.features list
"""

from __future__ import annotations

import argparse
import sys

from .supa import service_client


def _user_id(svc, email: str) -> str:
    page = 1
    while True:
        users = svc.auth.admin.list_users(page=page, per_page=200)
        for u in users:
            if (u.email or "").lower() == email.lower():
                return u.id
        if len(users) < 200:
            sys.exit(f"No user with email {email}")
        page += 1


def _team_id(svc, slug: str) -> str:
    rows = svc.table("teams").select("id").eq("slug", slug).execute().data
    if not rows:
        sys.exit(f"No lab with slug {slug}")
    return rows[0]["id"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["on", "off", "list"])
    p.add_argument("feature", nargs="?")
    who = p.add_mutually_exclusive_group()
    who.add_argument("--user", metavar="EMAIL")
    who.add_argument("--team", metavar="SLUG")
    args = p.parse_args()
    svc = service_client()

    if args.action == "list":
        for r in svc.table("team_features").select("feature, teams(slug)").execute().data or []:
            print(f"lab  {r['teams']['slug']:<30} {r['feature']}")
        for r in svc.table("user_features").select("feature, profiles(display_name)").execute().data or []:
            print(f"user {r['profiles']['display_name'] or '?':<30} {r['feature']}")
        return

    if not args.feature or not (args.user or args.team):
        p.error("on/off need a feature and --user or --team")
    if args.user:
        table, key = "user_features", {"user_id": _user_id(svc, args.user)}
    else:
        table, key = "team_features", {"team_id": _team_id(svc, args.team)}
    row = {**key, "feature": args.feature}
    if args.action == "on":
        svc.table(table).upsert(row, ignore_duplicates=True).execute()
    else:
        q = svc.table(table).delete()
        for k, v in row.items():
            q = q.eq(k, v)
        q.execute()
    print(f"{args.feature} {args.action} for {args.user or args.team}")


if __name__ == "__main__":
    main()
