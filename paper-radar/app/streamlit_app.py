"""paper-radar Streamlit shell.

Loads papers from the database (falling back to the JSON fixtures when the DB is
empty) and shows a searchable, tag-filterable list of paper cards. Kept
lightweight on purpose -- no heavy ML imports here, so the shell always launches.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Make the package importable when run via `streamlit run app/streamlit_app.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
            paper.get("abstract"),
            " ".join(paper.get("authors") or []),
            " ".join(paper.get("tags") or []),
            " ".join(paper.get("keywords") or []),
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


def _render_card(paper: dict) -> None:
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
            who = posted_by or "unknown"
            when = f" on {posted_at}" if posted_at else ""
            st.caption(f"📌 Shared by **{who}**{when}")

        # LLM summary (enrich stage) if present; otherwise fall back to the abstract.
        if paper.get("summary"):
            st.write(paper["summary"])
        elif paper.get("abstract"):
            with st.expander("Abstract"):
                st.write(paper["abstract"])

        tags = paper.get("tags") or []
        if tags:
            st.markdown(" ".join(f"`{t}`" for t in tags))

        keywords = paper.get("keywords") or []
        if keywords:
            st.caption("🔑 " + " · ".join(keywords[:8]))

        links = []
        if paper.get("url"):
            links.append(f"[paper]({paper['url']})")
        if paper.get("doi"):
            links.append(f"[doi](https://doi.org/{paper['doi']})")
        if paper.get("code_url"):
            links.append(f"[code]({paper['code_url']})")
        if paper.get("data_url"):
            links.append(f"[data]({paper['data_url']})")
        if links:
            st.markdown(" · ".join(links))


def main() -> None:
    st.set_page_config(page_title="paper-radar", page_icon="📡", layout="wide")
    st.title("📡 paper-radar")
    st.caption("Paper discovery for the breast tumor microenvironment lab.")

    papers = _load()

    with st.sidebar:
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
        _render_card(paper)


# `streamlit run` executes this file as the __main__ module.
if __name__ == "__main__":
    main()
