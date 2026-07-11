"""Atlas -- the Streamlit shell for paper-radar.

"Atlas" is the product/display name; the Python package stays ``paper_radar``.
Requires signing in (accounts are created with a team; new team names create
the team). Loads papers from the database (seeding the JSON fixtures when it is
empty) and shows a searchable, tag-filterable list of paper cards with
team-scoped comments and reactions, in a light or dark theme. Kept lightweight
on purpose -- no heavy ML imports here, so the shell always launches.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Make the package (repo root) and this app dir importable regardless of how the
# script is launched (`streamlit run`, AppTest, or from another CWD).
_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR.parent))
sys.path.insert(0, str(_APP_DIR))

import theme  # noqa: E402  (app/theme.py -- presentation helpers)

from paper_radar.auth import AuthError, get_team_name, login, signup  # noqa: E402
from paper_radar.social import (  # noqa: E402
    add_comment,
    list_comments,
    reaction_summary,
    toggle_reaction,
)
from paper_radar.store import list_papers  # noqa: E402


@st.cache_data(show_spinner=False)
def _load() -> list[dict]:
    """Load papers as plain dicts (cache-friendly, decoupled from the session)."""
    return [p.model_dump() for p in list_papers()]


def _format_posted_at(value: object) -> str | None:
    """Format a posted-at value (datetime or ISO string) as e.g. '16 Oct 2025 10:26'."""
    if not value:
        return None
    dt = value
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt  # show the raw string if it isn't ISO
    if isinstance(dt, datetime):
        # Drop a midnight time (date-only stamps) for a cleaner label.
        if (dt.hour, dt.minute) == (0, 0):
            return dt.strftime("%d %b %Y")
        return dt.strftime("%d %b %Y %H:%M")
    return str(dt)


def _matches(paper: dict, query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    haystack = " ".join(
        str(x)
        for x in (
            paper.get("title"),
            paper.get("summary"),
            " ".join(paper.get("authors") or []),
            " ".join(paper.get("tags") or []),
            paper.get("venue"),
        )
        if x
    ).lower()
    return q in haystack


def _all_tags(papers: list[dict]) -> list[str]:
    tags: set[str] = set()
    for p in papers:
        tags.update(p.get("tags") or [])
    return sorted(tags)


def _auth_gate() -> dict:
    """Return the signed-in user (id, name, team_id, team_name), or render the
    login/signup screen and stop the script."""
    if "user" in st.session_state:
        return st.session_state["user"]

    # Centered auth card.
    _, mid, _ = st.columns([1, 1.4, 1])
    ctx = mid.container(border=True)
    with ctx:
        theme.brand_header(size="sm")
        st.caption("Sign in to browse, comment on, and react to the lab's papers.")
        tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

    with tab_login, st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            try:
                user = login(email, password)
            except AuthError as exc:
                st.error(str(exc))
            else:
                st.session_state["user"] = {
                    "id": user.id,
                    "name": user.name,
                    "team_id": user.team_id,
                    "team_name": get_team_name(user.team_id),
                }
                st.rerun()

    with tab_signup, st.form("signup"):
        name = st.text_input("Name")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password (min. 8 characters)", type="password")
        team_name = st.text_input(
            "Team", help="Joins the team if it exists, otherwise creates it."
        )
        if st.form_submit_button("Create account", type="primary"):
            try:
                user = signup(name, email, password, team_name)
            except AuthError as exc:
                st.error(str(exc))
            else:
                st.session_state["user"] = {
                    "id": user.id,
                    "name": user.name,
                    "team_id": user.team_id,
                    "team_name": get_team_name(user.team_id),
                }
                st.rerun()

    st.stop()
    raise RuntimeError("unreachable")  # st.stop() never returns


def _render_reactions(paper_id: int, user: dict) -> None:
    summaries = reaction_summary(paper_id, user["team_id"], user["id"])
    # Trailing spacer columns keep the reaction pills compact on the left.
    cols = st.columns(len(summaries) + 3, gap="small")
    for col, s in zip(cols, summaries, strict=False):
        label = f"{s.emoji} {s.count}" if s.count else s.emoji
        if col.button(
            label,
            key=f"react-{paper_id}-{s.emoji}",
            type="primary" if s.mine else "secondary",
            help="Click to toggle your reaction (visible to your team).",
        ):
            toggle_reaction(paper_id, user["id"], user["team_id"], s.emoji)
            st.rerun()


def _render_comments(paper_id: int, user: dict) -> None:
    comments = list_comments(paper_id, user["team_id"])
    # Expander labels are plain text (no SVG), so this stays wordy rather than iconized.
    label = f"Comments · {len(comments)}" if comments else "Add a comment"
    with st.expander(label):
        for c in comments:
            theme.comment_bubble(c.author, _format_posted_at(c.created_at), c.body)
        with st.form(key=f"comment-{paper_id}", clear_on_submit=True):
            body = st.text_area(
                "Add a comment",
                placeholder="Visible to your whole team …",
                label_visibility="collapsed",
            )
            if st.form_submit_button("Post") and body.strip():
                add_comment(paper_id, user["id"], user["team_id"], body)
                st.rerun()


def _render_card(paper: dict, user: dict) -> None:
    title = paper.get("title") or paper.get("url") or "(untitled)"
    with st.container(border=True):
        st.markdown(f"### {title}")

        meta_bits = []
        authors = paper.get("authors") or []
        if authors:
            shown = ", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "")
            meta_bits.append(shown)
        if paper.get("venue"):
            meta_bits.append(str(paper["venue"]))
        if paper.get("year"):
            meta_bits.append(str(paper["year"]))
        if meta_bits:
            st.caption(" · ".join(meta_bits))

        # Who shared it in Teams, and when.
        posted_by = paper.get("posted_by")
        posted_at = _format_posted_at(paper.get("posted_at"))
        if posted_by or posted_at:
            theme.shared_by(posted_by or "unknown", posted_at)

        if paper.get("summary"):
            st.write(paper["summary"])

        theme.pills(paper.get("tags") or [])

        links = []
        if paper.get("url"):
            links.append(f"[paper]({paper['url']})")
        if paper.get("code_url"):
            links.append(f"[code]({paper['code_url']})")
        if paper.get("data_url"):
            links.append(f"[data]({paper['data_url']})")
        if links:
            st.markdown(" · ".join(links))

        # Team-scoped social layer (needs a persisted paper id).
        if paper.get("id") is not None:
            _render_reactions(paper["id"], user)
            _render_comments(paper["id"], user)


def main() -> None:
    st.set_page_config(page_title=theme.APP_NAME, page_icon="🧭", layout="wide")
    # Read the theme choice before injecting CSS. The toggle (rendered in the
    # sidebar below) persists its value in session_state under this key, so on
    # the rerun after a flip this already reflects the new choice.
    theme.inject(dark=st.session_state.get("pr_dark", False))
    user = _auth_gate()

    theme.brand_header()
    st.caption("Paper discovery for the breast tumor microenvironment lab.")

    papers = _load()

    with st.sidebar:
        theme.account_card(user["name"], user.get("team_name"))
        st.toggle("Dark mode", key="pr_dark")
        if st.button("Log out", use_container_width=True):
            del st.session_state["user"]
            st.rerun()
        st.markdown("---")
        st.header("Filters")
        query = st.text_input("Search", placeholder="title, author, summary, tag …")
        selected_tags = st.multiselect("Tags", _all_tags(papers))
        st.markdown("---")
        st.caption(f"{len(papers)} paper(s) loaded.")
        if st.button("Reload"):
            _load.clear()
            st.rerun()

    filtered = [
        p
        for p in papers
        if _matches(p, query)
        and (not selected_tags or set(selected_tags).issubset(set(p.get("tags") or [])))
    ]

    st.write(f"**{len(filtered)}** of {len(papers)} papers")
    if not filtered:
        st.info("No papers match the current filters.")
    for paper in filtered:
        _render_card(paper, user)


# `streamlit run` executes this file as the __main__ module.
if __name__ == "__main__":
    main()
