# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-01

### Added
- Meal planning Phase 2.5: AI-assisted dinner suggestion. New
  `meal_planner` config block (cuisines, pantry staples, restrictions,
  per-weekday overrides, optional shopping list target) drives a
  server-side prompt builder that calls `ai_task.generate_data`. Three
  new services: `familyboard.suggest_meal` (with optional `date`),
  `familyboard.accept_meal_suggestion`, and
  `familyboard.clear_meal_suggestion`. New `sensor.familyboard_meal_suggestion`
  exposes the latest suggestion (state = title, attrs = date / reason
  / ingredients / generated_at). Dashboard chip "Maaltijd" opens a
  popup with Vandaag/Morgen/Overmorgen quick picks and an Accept that
  creates the calendar event and appends ingredients to the configured
  shopping list. Suggestion persists across restarts.
- Options-flow step **Maaltijdplanner (AI)** for editing the
  `meal_planner` block from the UI (AI task entity, shopping list,
  max minutes, cuisines / pantry / restrictions / extra notes — all
  multi-line, one item per line). `day_overrides` remain YAML-only
  for now and are preserved across UI edits.
- `familyboard-chores-card`: new `show_shared` option (default `true`) to hide
  shared ("algemene") chores, and a `member: shared` value that turns the
  card into a shared-only view with an "Algemene taken" header. The card
  editor exposes `member` as a dropdown of configured family members plus an
  "Algemene (gedeeld)" option.

## [0.2.1] - 2026-04-29

### Changed
- `familyboard-calendar-card` day / 2-day / week / work-week / 2-week views
  now render multi-day all-day events as a single continuous bar across the
  day columns (matching the month view), with `‹` / `›` arrows on segments
  that continue beyond the visible range. Single-day events that span
  (almost) a full 24h (e.g. an "all-day" entry imported with explicit
  00:00–23:59 times) are also promoted to the all-day row instead of
  rendering as a 00:00 block in the time grid. Bars are stacked
  longest-span first so multi-day events sit on top.

## [0.2.0] - 2026-04-28

### Added
- Native month view in `familyboard-calendar-card` (replaces the Phase 3
  placeholder): 6×7 grid with multi-member gradient pills, weather badge and
  today/other-month/weekend styling. Week rows grow to fit all events — no
  more `+N meer` overflow truncation.
- `familyboard-calendar-card`: `show_navigation: false` now actually hides
  the prev/today/next buttons in the card header.
- Multi-day events render as continuous bars across the month grid (Google
  Calendar style), with `‹` / `›` arrows on segments that continue into the
  previous or next week.
- New view options: `today_tomorrow` (today + tomorrow side-by-side) and
  `work_week` (Mon–Fri of current week). Wired through the calendar card,
  chores card, list-mode strategy and translations (NL/EN).
- Week start in `familyboard-calendar-card` now follows the HA user profile
  (`hass.locale.firstWeekday`) for week, two-weeks and month grid headers.
  Werkweek blijft altijd ma–vr.
- `familyboard-view-card` accepts `hidden_options:` and `visible_options:`
  to hide/whitelist chips per dashboard without touching the select entity.
  Both are now exposed in the visual editor (only one shown at a time;
  `visible_options` takes precedence at runtime).
- `familyboard-calendar-card`: new **list** layout that groups events by day
  (large date number, weekday short name, weather chip, color-bar per event,
  reminders inline). Selected via the new `layout_entity` config option,
  intended to be bound to `select.familyboard_layout` so the existing
  `familyboard-view-card` toggles between time-grid and list in place.
- `familyboard-filter-card` and `familyboard-view-card`: new `alignment`
  config option (`start` / `center` / `end` / `justify`, with friendly
  aliases `left` / `middle` / `right` / `uitlijnen`). Forwarded to the
  underlying `mushroom-chips-card` and exposed in each card's visual editor.

### Fixed
- `familyboard-calendar-card`: day-header date and weather chip overlapped
  on narrow widths (portrait week / 2-weeks view). Header is now a flex row
  with container-query breakpoints that drop weather temperatures (then the
  whole weather chip) when columns become too narrow.

### Changed
- Dev/test dependencies bumped to match HA 2026.4: `homeassistant` 2026.4.4,
  `pytest` ≥9.0.3, `pytest-asyncio` ≥1.3.0, `pytest-cov` ≥7.1.0,
  `pytest-homeassistant-custom-component` ≥0.13.324.
- CI: `actions/checkout@v6` everywhere; tests workflow now runs on
  Python 3.14 (required by the new `pytest-homeassistant-custom-component`).

## [0.1.0] - 2026-04-23

Initial public release.

### Added
- Per-member calendar proxies (primary + extra calendars), Google Tasks filtered out.
- Cross-member "Alles" calendar with deduplicated multi-member events
  (`[FB:members=...;colors=...]` marker, multi-color borders).
- Trash collection calendar from configured `sensor.*` entities, with optional
  auto-generated chores via `TrashChoreManager` (bins 21:00 day before, kliko
  07:00 collection day; dedup via `.storage/familyboard_trash_chores`).
- `sensor.familyboard_chores` — combined per-member chore list, sorted
  overdue → upcoming → no-date, optionally cross-matched with calendar tasks.
- `sensor.familyboard_progress` — daily per-member completion percentages.
- `sensor.familyboard_members` — member metadata, shared calendars, shared chores.
- Interactive snooze reminders via `mobile_app` actionable notifications,
  persisted across HA restarts and away-aware.
- Add-event form entities: `select.familyboard_calendar`,
  `select.familyboard_view`, `select.familyboard_event_member`,
  `select.familyboard_event_calendar` (cascading), `text.familyboard_event_title`,
  `switch.familyboard_event_all_day`,
  `datetime.familyboard_event_{start,end,day_start,day_end}`.
- **FR-12 Event countdown**: `text.familyboard_countdown_label` and
  `datetime.familyboard_countdown_date` entities and a
  `custom:familyboard-countdown-card` Lovelace card. The card shows
  "⏳ Nog N dagen tot LABEL!", "⏳ Morgen is het LABEL!" or
  "🎉 Vandaag is het LABEL!", hides itself when no label is set, and
  auto-clears the label one tick after the date passes. Tap the gear icon to
  edit label + date directly on the kiosk (no admin login needed).
- Visual editors for every FamilyBoard custom card (`progress`, `chores`,
  `calendar`, `filter`, `view`). Each card exposes `getConfigElement()` /
  `getStubConfig()` returning a tiny `ha-form`-driven editor, so the dashboard
  card picker no longer shows "Visuele editor niet ondersteund". Schema covers
  the keys the cards already read; dict-typed options (`colors`, `names`,
  `filter_map`, `shared_calendars`, `member_entities`, `icons`, `extra_chips`)
  remain YAML-only.
- `custom:familyboard-view-card` Lovelace card that renders chip selectors for
  any FamilyBoard `select` entity (default `select.familyboard_view`). Labels
  are pulled from Home Assistant state translations via
  `hass.formatEntityState`, so adding a new language only requires updating
  `translations/<lang>.json`.
- Stable English option keys for `select.familyboard_view`
  (`today`/`tomorrow`/`week`/`two_weeks`/`month`) and
  `select.familyboard_layout` (`list`/`agenda`). User-visible labels are driven
  by the `entity.select.{view,layout}.state.*` translation blocks.
- Meal planning Phase 1: optional `meal_calendar` config key,
  `sensor.familyboard_meals` exposing tonight's meal and a 7-day week
  attribute, plus a "Vanavond" + week-strip + "Maaltijd plannen" block in the
  dashboard.
- Meal placeholders: titles `-`, `--`, `?`, `geen`, `none`, `n/a`
  (case-insensitive) mark a day as deliberately skipped. They render as 🚫 on
  the board and do not trigger the unplanned-meal alert.
- `binary_sensor.familyboard_meals_unplanned` (device class `problem`) is on
  whenever any of the next 7 days has no meal entry at all (skipped
  placeholders count as planned). Attributes expose `unplanned_dates`,
  `count`, and `next_unplanned`.
- Meal planning Phase 2: `sensor.familyboard_recent_meals` scoring the last
  90 days of meal events (`uses − recency_penalty`, capped at 12 distinct
  titles) and a Bubble Card pop-up (`#meal-picker`) on the dashboard that
  lists the top picks as tappable buttons creating an all-day event for today
  on the meals calendar.
- Lovelace cards (vanilla JS, no build step), auto-registered via Lovelace
  resources API: `familyboard-calendar-card`, `familyboard-chores-card`,
  `familyboard-filter-card`, `familyboard-progress-card`,
  `familyboard-countdown-card`, `familyboard-view-card`, plus the
  `familyboard-strategy` dashboard strategy.
- Dev container (`.devcontainer.json`) plus `scripts/setup`, `scripts/develop`,
  `scripts/lint`, `requirements-dev.txt` and a minimal
  `config/configuration.yaml` for running a local Home Assistant against this
  repo without bind mounts or symlinks.
- `.vscode/launch.json` with launch configs for HA (`scripts/develop`
  equivalent under debugpy) and `pytest` on the current file.
- HACS + manual installation paths; YAML and config-flow setup.

### Notes
- Repository was opened to the public at this release; prior internal commit
  history was discarded to remove personal data and is not retained.

