# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
