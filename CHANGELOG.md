# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Meal planning Phase 1: optional `meal_calendar` config key, new
  `sensor.familyboard_meals` exposing tonight's meal and a 7-day week
  attribute, plus a "Vanavond" + week-strip + "Maaltijd toevoegen"
  block in the dashboard.
- Auto-seeded **FamilyBoard** sidebar dashboard. The integration now
  creates a storage-mode Lovelace dashboard at `/familyboard` on first
  startup, rendered via the `custom:familyboard` strategy. Users can
  edit the dashboard freely afterwards; the seed only runs when no
  dashboard with that URL path exists.
- Dev container (`.devcontainer.json`) plus `scripts/setup`,
  `scripts/develop`, `scripts/lint`, `requirements-dev.txt` and a
  minimal `config/configuration.yaml` for running a local Home
  Assistant against this repo without bind mounts or symlinks. See
  `plans/devcontainer.md` and the new *Development \u2192 Dev container*
  section in `README.md`.
- `.vscode/launch.json` with launch configs for HA (`scripts/develop`
  equivalent under debugpy) and `pytest` on the current file.

### Changed
- `familyboard-filter-card` now styles selection state via `card-mod`'s
  `mushroom-chip$` selector targeting the inner `.chip` element. The
  previous `:host`/`ha-card` selector never painted because the chip
  itself sits in front of those elements, so the selected member never
  visually highlighted.

### Fixed
- Calendar filter `select` is now pinned to `select.familyboard_calendar`
  via `suggested_object_id`, matching the constant used by the dashboard
  and frontend cards. Previously the translation_key suffix produced
  `select.familyboard_calendar_filter`, breaking every chip tap with
  *Referenced entities … are missing or not currently available*.
  Existing wrong entity_ids are migrated automatically on startup.
- `familyboard-strategy` now slugifies member names with the same rules
  Home Assistant uses (non-alphanumeric → `_`), so members like
  `Dev A` resolve to `calendar.familyboard_dev_a` instead of
  `calendar.familyboard_dev a` (which yielded HTTP 400 from the
  calendar fetch).

## [0.1.0] - 2026-04-20

Initial tracked release.

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
- Lovelace cards (vanilla JS, no build step), auto-registered via Lovelace
  resources API: `familyboard-calendar-card`, `familyboard-chores-card`,
  `familyboard-filter-card`, `familyboard-progress-card`, plus
  `familyboard-strategy` dashboard strategy.
- HACS + manual installation paths; YAML and config-flow setup.
