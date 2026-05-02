"""Sanity tests for the event-themes.js keyword map.

The themes module is the single source of truth for the calendar
card's keyword -> theme matcher. We don't run JS in CI, but we can
parse the keyword literal out of the source and verify the data
shape, the fallback behavior (no match -> None), and routing for
the real-world titles seen on the dev tablet.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

import pytest

FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "familyboard"
    / "frontend"
)
THEMES_JS = FRONTEND_DIR / "event-themes.js"
ICONS_DIR = FRONTEND_DIR / "icons" / "events"

EXPECTED_THEMES = {
    "birthday",
    "beer",
    "party",
    "school",
    "phone",
    "work",
    "badminton",
    "fishing",
    "walking",
    "hiking",
    "outdoors",
    "gym",
    "doctor",
    "bbq",
    "food",
    "camping",
    "travel",
    "family",
    "friends",
    "shopping",
    "cleaning",
    "pet",
    "music",
}


def _extract_keyword_map() -> dict[str, list[str]]:
    """Parse the EVENT_THEME_KEYWORDS literal out of the JS module."""
    text = THEMES_JS.read_text(encoding="utf-8")
    m = re.search(
        r"export\s+const\s+EVENT_THEME_KEYWORDS\s*=\s*(\{.*?\n\});",
        text,
        re.DOTALL,
    )
    assert m, "EVENT_THEME_KEYWORDS literal not found in event-themes.js"
    blob = m.group(1)
    blob = re.sub(r"^(\s*)([a-z_][a-z0-9_]*)\s*:", r'\1"\2":', blob, flags=re.M)
    blob = re.sub(r",\s*([\]}])", r"\1", blob)
    return json.loads(blob)


def _tokenize(s: str) -> list[str]:
    decomposed = unicodedata.normalize("NFD", s.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", stripped) if t]


def _build_index(themes: dict[str, list[str]]) -> dict[str, str]:
    idx: dict[str, str] = {}
    for theme, words in themes.items():
        for w in words:
            tokens = _tokenize(w)
            if not tokens:
                continue
            first = tokens[0]
            if first not in idx:
                idx[first] = theme
    return idx


_OVERRIDE_RE = re.compile(r"\[FB:theme=([a-z0-9_-]+)\]", re.IGNORECASE)


def _event_theme(
    title: str,
    description: str | None,
    themes: dict[str, list[str]],
    index: dict[str, str],
) -> str | None:
    if description:
        m = _OVERRIDE_RE.search(description)
        if m:
            key = m.group(1).lower()
            if key == "none":
                return None
            if key in themes:
                return key
    for tok in _tokenize(title):
        if tok in index:
            return index[tok]
    return None


# --- Static data tests ---


def test_event_themes_js_exists() -> None:
    """Catch accidental relocation."""
    assert THEMES_JS.is_file(), THEMES_JS


def test_keyword_map_has_expected_themes() -> None:
    """All 19 themes are present, no extras."""
    themes = _extract_keyword_map()
    assert set(themes) == EXPECTED_THEMES


def test_every_theme_has_keywords_and_svg() -> None:
    """Each theme key needs at least one keyword and a matching SVG."""
    themes = _extract_keyword_map()
    empty = [k for k, v in themes.items() if not v]
    assert not empty, f"themes with no keywords: {empty}"
    missing = [k for k in themes if not (ICONS_DIR / f"{k}.svg").is_file()]
    assert not missing, f"themes without SVG asset: {missing}"


def test_no_default_svg() -> None:
    """No-match must return None — default.svg was intentionally removed."""
    assert not (ICONS_DIR / "default.svg").exists()


def test_keywords_are_lowercase() -> None:
    """Keywords are matched after lowercasing — keep them lowercase."""
    themes = _extract_keyword_map()
    bad: list[str] = []
    for theme, words in themes.items():
        for w in words:
            if w != w.lower():
                bad.append(f"{theme}:{w}")
    assert not bad, f"non-lowercase keywords: {bad}"


@pytest.mark.parametrize("theme", sorted(EXPECTED_THEMES))
def test_svg_files_are_small(theme: str) -> None:
    """Themed event illustrations should stay under 25 KB each."""
    path = ICONS_DIR / f"{theme}.svg"
    assert path.is_file(), path
    size = path.stat().st_size
    assert size < 25 * 1024, f"{path.name} is {size} bytes — keep deco SVG < 25 KB"


# --- Routing tests (real titles from the dev tablet) ---


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Scouting", "outdoors"),
        ("Viscursus", "fishing"),
        ("Belafspraak dhr Oren", "phone"),
        ("Telefonisch contact ADHD", "phone"),
        ("Verjaardag Tim en Bram", "birthday"),
        ("Trouwdag Pa & Ma", "birthday"),
        ("Bros B4 Hos", "beer"),
        ("Naar de camping", "camping"),
        ("Wandeldozen", "walking"),
        ("Sponsor hike", "hiking"),
        ("Avond-4-daagse", "hiking"),
        ("Vakantie", "travel"),
        ("Badminton vrij spelen", "badminton"),
        ("Intake met Sylvia", "doctor"),
        ("BBQ bij de buren", "bbq"),
        ("Hands-On Cooking Class", "food"),
        ("Voetbal training", "gym"),
    ],
)
def test_keyword_routing(title: str, expected: str) -> None:
    """Real-world titles should route to the right theme."""
    themes = _extract_keyword_map()
    index = _build_index(themes)
    assert _event_theme(title, None, themes, index) == expected


@pytest.mark.parametrize(
    "title",
    ["Joanne laatste werkdag", "Hugo's", "x"],
)
def test_no_keyword_match_returns_none(title: str) -> None:
    """Titles with no keyword stay plain — no default fallback."""
    themes = _extract_keyword_map()
    index = _build_index(themes)
    assert _event_theme(title, None, themes, index) is None


def test_override_marker_picks_theme() -> None:
    """[FB:theme=<key>] in the description forces a theme."""
    themes = _extract_keyword_map()
    index = _build_index(themes)
    assert _event_theme("Whatever", "[FB:theme=party]", themes, index) == "party"


def test_override_none_suppresses_decoration() -> None:
    """[FB:theme=none] disables decoration even when a keyword matches."""
    themes = _extract_keyword_map()
    index = _build_index(themes)
    assert _event_theme("Verjaardag", "[FB:theme=none]", themes, index) is None


def test_override_unknown_theme_falls_through_to_keywords() -> None:
    """Unknown override keys are ignored; keyword matching still runs."""
    themes = _extract_keyword_map()
    index = _build_index(themes)
    assert _event_theme("Verjaardag", "[FB:theme=bogus]", themes, index) == "birthday"
