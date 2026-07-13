"""Visual theming for the Streamlit shell.

This is the "Option A" restyle: injected CSS plus a few small HTML helpers that
make the stock Streamlit app read like a modern web UI, without a React
rewrite. It ships a light *and* a dark palette (toggled in-app) and uses
`Lucide <https://lucide.dev>`_ icons wherever Streamlit lets us embed raw SVG
(brand mark, sidebar, share/comment chips). Reaction glyphs stay as emoji --
they are the reaction vocabulary itself, not chrome -- and Streamlit widget
*labels* (buttons, expanders) can't hold SVG, so those stay plain text.

Everything here is presentation only -- none of it touches the auth or social
logic. Design tokens live in one place (`_LIGHT` / `_DARK`) so a future React
port can lift them directly.

All helpers that embed user- or data-derived text HTML-escape it, since the app
injects raw HTML via ``unsafe_allow_html=True``.
"""

from __future__ import annotations

import html

import streamlit as st

APP_NAME = "Atlas"

# --- design tokens -------------------------------------------------------
# Indigo accent on a soft neutral canvas. Two palettes, one set of rules.
_LIGHT = {
    "accent": "#4f46e5",
    "accent2": "#8b5cf6",
    "accent_soft": "#eef0ff",
    "ink": "#1f2333",
    "muted": "#6b7185",
    "line": "#e6e8f0",
    "card": "#ffffff",
    "canvas": "#f4f5fb",
    "shadow": "0 10px 30px rgba(24, 27, 54, 0.09)",
    "shadow_sm": "0 1px 2px rgba(24, 27, 54, 0.05)",
}
_DARK = {
    "accent": "#7c7bff",
    "accent2": "#a78bfa",
    "accent_soft": "rgba(124, 123, 255, 0.16)",
    "ink": "#e8e9f2",
    "muted": "#9aa0b8",
    "line": "#2a2e44",
    "card": "#1a1d2b",
    "canvas": "#101220",
    "shadow": "0 14px 40px rgba(0, 0, 0, 0.45)",
    "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.3)",
}

# Deterministic avatar backgrounds (picked by hashing the name).
_AVATAR_COLORS = [
    "#6366f1", "#0ea5e9", "#10b981", "#f59e0b",
    "#ef4444", "#ec4899", "#8b5cf6", "#14b8a6",
]

# Inner elements of the Lucide icons we embed (24x24, stroke=currentColor).
_ICONS = {
    "compass": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411'
        'a2 2 0 0 1 1.265-1.265z"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<path d="M16 3.128a4 4 0 0 1 0 7.744"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<circle cx="9" cy="7" r="4"/>'
    ),
    "share": (
        '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>'
        '<circle cx="18" cy="19" r="3"/>'
        '<line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/>'
        '<line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>'
    ),
    "message": (
        '<path d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168'
        'l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719"/>'
    ),
}


def icon(name: str, size: int = 18, stroke: float = 2, color: str = "currentColor") -> str:
    """Return an inline Lucide SVG string, colored via ``color`` (a CSS value)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="vertical-align:middle;flex:0 0 auto">{_ICONS[name]}</svg>'
    )


def _root_block(pal: dict[str, str]) -> str:
    return ":root{" + "".join(f"--pr-{k.replace('_', '-')}:{v};" for k, v in pal.items()) + "}"


# Palette-independent rules -- everything references the --pr-* custom properties,
# so the same stylesheet renders either theme just by swapping the :root block.
_STATIC_CSS = """
/* No webfont @import: pulling Inter from fonts.googleapis.com leaks every
   visitor's IP to Google. Fall back to the system font stack instead. */
html, body, [class*="css"], [data-testid="stAppViewContainer"] {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
}

/* Repaint the base Streamlit surfaces so both themes are fully controlled. */
.stApp { background: var(--pr-canvas); color: var(--pr-ink); }
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stHeader"] { background: var(--pr-canvas); }
[data-testid="stSidebar"] { background: var(--pr-card); border-right: 1px solid var(--pr-line); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  color: var(--pr-muted) !important;
}
input, textarea { background: var(--pr-card) !important; color: var(--pr-ink) !important; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"] {
  background: var(--pr-card) !important;
}
[data-baseweb="select"] > div {
  background: var(--pr-card) !important; color: var(--pr-ink) !important;
  border-color: var(--pr-line) !important;
}
[data-baseweb="tag"] {
  background: var(--pr-accent-soft) !important; color: var(--pr-accent) !important;
}

/* Tighter, centered reading column. */
.main .block-container { max-width: 860px; padding-top: 2.2rem; padding-bottom: 4rem; }

/* Cards: st.container(border=True) renders this wrapper. */
[data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--pr-line) !important;
  border-radius: 16px !important;
  background: var(--pr-card);
  padding: 0.4rem 0.4rem;
  box-shadow: var(--pr-shadow-sm);
  transition: box-shadow 0.18s ease, transform 0.18s ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: var(--pr-shadow); transform: translateY(-1px);
}
[data-testid="stVerticalBlockBorderWrapper"] h3 {
  font-size: 1.18rem; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 0.2rem;
}

/* Buttons -> rounded pills. */
.stButton > button {
  border-radius: 999px; font-weight: 600; border: 1px solid var(--pr-line);
  padding: 0.3rem 0.9rem; transition: all 0.15s ease;
}
.stButton > button[kind="secondary"] { background: var(--pr-card); color: var(--pr-ink); }
.stButton > button[kind="primary"] {
  background: var(--pr-accent); border-color: var(--pr-accent); color: #fff;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.08); }
.stButton > button[kind="secondary"]:hover {
  border-color: var(--pr-accent); color: var(--pr-accent);
}

.stTextInput input, .stTextArea textarea,
.stMultiSelect [data-baseweb="select"] > div { border-radius: 10px !important; }

/* Expander (comments). */
[data-testid="stExpander"] {
  border: 1px solid var(--pr-line); border-radius: 12px;
  background: var(--pr-canvas); overflow: hidden;
}
[data-testid="stExpander"] summary {
  font-weight: 600; font-size: 0.9rem; color: var(--pr-ink);
}

/* Custom components. */
.pr-avatar {
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; color: #fff; font-weight: 600; flex: 0 0 auto;
}
.pr-chip {
  display: inline-flex; align-items: center; gap: 0.45rem;
  font-size: 0.82rem; color: var(--pr-muted);
}
.pr-pills { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.5rem 0; }
.pr-pill {
  background: var(--pr-accent-soft); color: var(--pr-accent);
  border-radius: 999px; padding: 0.12rem 0.6rem; font-size: 0.76rem; font-weight: 600;
}
.pr-account {
  display: flex; align-items: center; gap: 0.6rem; padding: 0.7rem;
  border: 1px solid var(--pr-line); border-radius: 12px;
  background: var(--pr-canvas); margin-bottom: 0.4rem;
}
.pr-account .pr-name { font-weight: 700; line-height: 1.15; color: var(--pr-ink); }
.pr-account .pr-team {
  font-size: 0.78rem; color: var(--pr-muted);
  display: inline-flex; align-items: center; gap: 0.3rem;
}
.pr-comment { display: flex; gap: 0.6rem; padding: 0.5rem 0; }
.pr-comment-head { font-size: 0.86rem; margin-bottom: 0.15rem; color: var(--pr-ink); }
.pr-comment-time { color: var(--pr-muted); font-size: 0.78rem; margin-left: 0.35rem; }
.pr-comment-body { font-size: 0.92rem; line-height: 1.45; color: var(--pr-ink); }
.pr-brand {
  display: flex; align-items: center; gap: 0.5rem;
  font-weight: 800; letter-spacing: -0.02em; margin-bottom: 0.1rem;
}
.pr-brand .pr-word {
  background: linear-gradient(90deg, var(--pr-accent), var(--pr-accent2));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
"""


def inject(dark: bool = False) -> None:
    """Inject the stylesheet for the chosen theme (call once, before widgets)."""
    css = _root_block(_DARK if dark else _LIGHT) + _STATIC_CSS
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _color_for(seed: str) -> str:
    return _AVATAR_COLORS[sum(seed.encode()) % len(_AVATAR_COLORS)]


def _initials(name: str) -> str:
    parts = [p for p in name.replace("@", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def avatar_html(name: str, size: int = 30) -> str:
    """A circular initials avatar (color derived from the name)."""
    font = max(11, size // 2)
    return (
        f'<span class="pr-avatar" style="width:{size}px;height:{size}px;'
        f'font-size:{font}px;background:{_color_for(name)};">'
        f"{html.escape(_initials(name))}</span>"
    )


def brand_header(size: str = "lg") -> None:
    px = 34 if size == "lg" else 26
    word = "2.05rem" if size == "lg" else "1.55rem"
    st.markdown(
        f'<div class="pr-brand" style="font-size:{word}">'
        f'{icon("compass", size=px, stroke=2.2, color="var(--pr-accent)")}'
        f'<span class="pr-word">{APP_NAME}</span></div>',
        unsafe_allow_html=True,
    )


def account_card(name: str, team: str | None) -> None:
    team_line = ""
    if team:
        team_line = (
            f'<div class="pr-team">{icon("users", size=13, color="var(--pr-muted)")}'
            f"{html.escape(team)}</div>"
        )
    st.markdown(
        f'<div class="pr-account">{avatar_html(name, 38)}'
        f'<div><div class="pr-name">{html.escape(name)}</div>{team_line}</div></div>',
        unsafe_allow_html=True,
    )


def pills(tags: list[str]) -> None:
    if not tags:
        return
    inner = "".join(f'<span class="pr-pill">{html.escape(t)}</span>' for t in tags)
    st.markdown(f'<div class="pr-pills">{inner}</div>', unsafe_allow_html=True)


def shared_by(who: str, when: str | None) -> None:
    when_txt = f" · {html.escape(when)}" if when else ""
    st.markdown(
        f'<div class="pr-chip">{icon("share", size=15, color="var(--pr-muted)")}'
        f'{avatar_html(who, 22)}<span>Shared by '
        f'<b style="color:var(--pr-ink)">{html.escape(who)}</b>{when_txt}</span></div>',
        unsafe_allow_html=True,
    )


def comment_bubble(author: str, when: str | None, body: str) -> None:
    when_txt = f'<span class="pr-comment-time">{html.escape(when)}</span>' if when else ""
    safe_body = html.escape(body).replace("\n", "<br>")
    st.markdown(
        f'<div class="pr-comment">{avatar_html(author, 30)}'
        f'<div><div class="pr-comment-head"><b>{html.escape(author)}</b>{when_txt}</div>'
        f'<div class="pr-comment-body">{safe_body}</div></div></div>',
        unsafe_allow_html=True,
    )
