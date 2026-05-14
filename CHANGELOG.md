# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Chore urgency styling** — chores card now highlights overdue
  (red), due-soon (orange) and due-today (blue) rows with a tinted
  background and colored left border. Each tier is independently
  togglable and color-customisable via the new *Display* sub-item.
- **Display sub-item** (singleton) — configurable urgency tier
  toggles and accent colors. Settings → Devices & Services →
  FamilyBoard → ➕ Display. Also available as `display:` in YAML.
- **Confetti celebration** — the progress card fires a full-screen
  confetti burst when a member reaches 100 % completion.
- **Chore-completion history (energy-dashboard pattern).** Each tick
  the coordinator now records every disappearing chore into a
  persistent log:
  - `sensor.familyboard_completions_total_<member>` — one cumulative
    counter per member (`state_class: total_increasing`, unit
    `tasks`). Works out of the box with HA's `statistics-graph`
    card, statistics-card, energy-style aggregations and the
    long-term statistics database for hourly/daily/weekly/monthly
    rollups. Counter is monotonic and only resets on integration
    uninstall.
  - `sensor.familyboard_recent_chores` — state = today's count;
    `attributes.entries` carries the latest 500 entries (90-day
    cap, whichever hits first) for the new recent-list card.
  Attribution honors the Phase 4 claim model: unclaimed shared
  chores are logged with `member: null` and credit no counter.
- **`custom:familyboard-recent-chores-card`** — compact list card
  showing the most recent completions with a member-color dot,
  source badge (Persoonlijk / Gedeeld) and a Dutch relative
  timestamp ("net", "5 min geleden", "gisteren"…). Auto-registered
  via Lovelace resources.
- **Tap-to-claim shared chores.** Each shared chore row now has a
  *Claim* chip; tapping it opens a small picker (`Wie pakt dit op?`)
  with one button per family member plus *Vrijgeven*. Once a member
  claims a chore the chip locks in their color/avatar so the
  household sees who took it.
- **`familyboard.claim_chore` service** — `{uid, member}` (omit
  `member` to release). Drives the same logic as the chip; usable
  from automations or scripts.
- **Claim persistence.** Active claims survive HA restarts in
  `.storage/familyboard_chore_claims`. Stale claims (UID gone, or
  member removed from config) are pruned automatically on the next
  coordinator refresh.

### Changed
- **BREAKING — shared-chore progress crediting.** Completing an
  *unclaimed* shared chore no longer increments any member's
  progress ring. Claim the chore first; on completion only the
  claimer is credited. Previously every listed member of a shared
  chore got +1 — that "credit everyone" behavior is replaced by
  Option A (visibility ≠ credit). Personal chores are unchanged.
- **Visibility of claimed shared chores** narrows to the claimer:
  once Berry claims `todo.trash`, Sylvia and Cas no longer see it
  on their per-member cards. The Algemene card still shows it,
  with Berry's badge.

### Fixed
- **Shared chores no longer disappear from the Algemene card** when
  `select.familyboard_view` is narrowed (e.g. `today` or `2_days`)
  and the chore's due date falls outside that window. Shared chores
  now bypass the view-window trim while personal chores continue
  to honor it.
- **Shared chores without a UID** are now deduplicated across
  members by `(todo_entity, summary, due)` so `todo` integrations
  that omit UIDs render one row instead of N copies on the
  Algemene card.
- **Frontend chores card view filter** now mirrors the canonical
  `VIEW_OPTIONS` keys (`today`, `2_days`, `3_days`, `work_week`,
  `week`, `two_weeks`, `month`). Previously selecting `2_days` or
  `3_days` silently fell through to "no client-side filter".

### Changed
- **Progress rings count only today's chores** — rings now track
  chores that are due today, overdue, or have no due date.
  Previously every chore in the todo list inflated the total.
  Completed counts are derived from the persisted history log so
  they survive HA restarts.
- A typo in `shared_chores: members:` (e.g. wrong case or unknown
  name) now logs a single WARNING per `(entity, member)` pair
  instead of silently dropping the chore from every card.
- A `todo.*` entity that appears in both a member's personal
  `chores:` list **and** in `shared_chores:` now logs a WARNING
  at coordinator init explaining that the personal copy will
  shadow the shared one.

### Removed
- **Dropped `week-planner-card`, `atomic-calendar-revive` and
  `config-template-card` dependencies.** The dashboard strategy no
  longer generates cards from these integrations; all calendar
  rendering is handled by the built-in `familyboard-calendar-card`.

## [0.3.0] - 2026-05-03

### Added
- **Calendar category in sub-item forms.** Member, Extra calendar and
  Shared calendar sub-items now expose a `category` dropdown
  (`personal` / `work` / `school` / `hobby` / `family` / `other`),
  matching the YAML schema. Previously the field was YAML-only, so
  UI users couldn't tag their calendars for the category filter chips.
- **Consolidated `meals:` YAML block.** The legacy top-level
  `meal_calendar:` and `meal_planner:` keys have been folded into a
  single `meals:` block (with `calendar:` nested inside). Reads cleaner
  and matches the singleton sub-item.
- **Subentry-based configuration.** Members, extra calendars, shared
  calendars, shared chores, trash sensors, the meal planner and
  per-weekday meal overrides are now individual *sub-items* on the
  integration page (Settings → Devices & Services → FamilyBoard →
  click ➕). Add, edit and remove each one separately instead of
  navigating one giant options-flow form.
- **Decorative event illustrations.** Opt-in `event_images: true`
  card option on `custom:familyboard-calendar-card` inlines a
  full-color illustration into timed event tiles, picked from the
  title via a built-in NL + EN keyword map (23 themes: birthday,
  beer, bbq, party, school, phone, work, badminton, fishing,
  walking, hiking, outdoors, gym, doctor, food, camping, travel,
  family, friends, shopping, cleaning, pet, music). SVGs are
  sourced from [unDraw](https://undraw.co/) and re-mapped so every
  fill resolves to a `--fb-deco-*` CSS variable (`accent`,
  `accent-2`, `dark`, `grey`, `skin`, `light`) — themable per tile,
  per member, or globally via a HA theme. A handful of scenes
  (`friends`, `beer`, `fishing`) ship with per-theme overrides where
  the defaults under-read. Tile height decides the layout: ≥ 120 px
  gets a full-bleed banner; 56–120 px gets a corner badge at
  bottom-right that scales 4:3 with the tile (capped at 96×72);
  shorter/compact tiles stay plain. Pure client-side, deterministic,
  offline. **No fallback** — when no keyword matches, the tile
  renders plainly. Override per event with `[FB:theme=<key>]`, or
  suppress with `[FB:theme=none]`. Add new themes by dropping a
  themable SVG into `frontend/icons/events/`.
- **Progress card celebration** — when a member's daily progress ring
  hits 100% the ring briefly pulses with a glow and a small confetti
  burst, drawing attention to the "all done" moment without adding any
  extra noise to the rest of the dashboard. Animation is suppressed
  for users with `prefers-reduced-motion: reduce`.
- **Meal planning Phase 2.5** — AI-assisted dinner suggestion. New
  `meal_planner` config block (cuisines, pantry staples, restrictions,
  per-weekday overrides, optional shopping list target) drives a
  server-side prompt builder that calls `ai_task.generate_data`. New
  services: `familyboard.suggest_meal` (with optional `date`),
  `familyboard.accept_meal_suggestion` and
  `familyboard.clear_meal_suggestion`. New
  `sensor.familyboard_meal_suggestion` exposes the latest suggestion
  (state = title; attrs = date / reason / ingredients / generated_at)
  and persists across restarts. Dashboard chip "Maaltijd" opens a popup
  with Vandaag/Morgen/Overmorgen quick picks; Accept creates the
  calendar event and appends ingredients to the configured shopping
  list. Editable from the UI via a new options-flow step
  **Maaltijdplanner (AI)** (AI task entity, shopping list, max minutes,
  cuisines / pantry / restrictions / extra notes — multi-line, one per
  line). `day_overrides` remain YAML-only and are preserved across UI
  edits.
- **Calendar category filter** — new `category:` field on `members[]`,
  `members[].extra_calendars[]` and `shared_calendars[]`, one of
  `personal`, `work`, `school`, `hobby`, `family`, `other` (default
  `personal` for both members and shared calendars). One
  `switch.familyboard_category_<key>` is created per category in use
  (default on, restored on restart) and stale switches are purged from
  the entity registry when the matching category disappears from YAML.
  The dashboard strategy auto-renders a chip row above the calendar;
  `familyboard-calendar-card` auto-discovers
  `switch.familyboard_category_*` (override via `category_switches:`)
  and hides events whose categories are all currently disabled. Trash
  and reminders are never filtered. New standalone
  `custom:familyboard-category-card` for manual dashboards.
- **Chores card scoping** — `familyboard-chores-card` gains
  `show_shared` (default `true`) to hide shared ("algemene") chores,
  and a `member: shared` value that turns the card into a shared-only
  view with an "Algemene taken" header. The card editor exposes
  `member` as a dropdown of configured family members plus an
  "Algemene (gedeeld)" option.
- **Trash chore granularity** — `trash[].reminder_bins` and
  `trash[].reminder_kliko` (both default `true`) skip just one of the
  two auto-created chores per trash type (e.g. `reminder_bins: false`
  to keep only the "kliko aan de weg" reminder).
- **Calendar entity attributes** — `FamilyBoardProxyCalendar` now
  exposes `color` and `category` as state attributes so frontend cards
  inherit them from `configuration.yaml` automatically. Dashboard YAML
  no longer needs a hardcoded `colors:` map on
  `familyboard-calendar-card`.
- README *Recommended palette* (pastel blue/green/pink) for member
  colors. Optional — auto-contrast text keeps any palette readable.

### Changed
- **Meal weekday override sub-item is now self-explanatory.** Renamed
  the entry type to *Meal weekday override* and added a description
  explaining that the note is appended to the AI prompt and
  `max_minutes` overrides the planner default for that one day.
- **Member filter merged into the progress card.** `familyboard-progress-card`
  now accepts `filter_entity` + `selectable: true`; each tile becomes a
  button that writes to the filter `select`, and the selected member's
  name gets a 2 px underline in the member's color (every tile is
  underlined when the filter is `Alles`). Tile DOM was reordered so
  the member name sits above the ring. The default dashboard strategy
  uses this built-in filter and no longer renders a separate
  `familyboard-filter-card` row, freeing the side stack for countdown
  + reminders. The standalone filter card remains fully supported for
  hand-built dashboards.
- **Subentry migration.** Config-entry version bumped to **2**.
  Existing v1 entries are migrated automatically on first start: every
  list item in `entry.options` becomes a subentry with a stable
  `unique_id`. Migration is idempotent.
- YAML configuration still works and is now **upserted** into
  sub-items by stable identity. Sub-items you added via the UI
  without a YAML twin are preserved across re-imports.
- **Trash auto-chore reminders are opt-in for new entries.** When you
  add a trash sub-item via the UI, both *empty bins* and *kliko at
  the curb* default to **off**; tick the boxes you want. Existing
  YAML / migrated v1 entries keep the legacy default-on behaviour
  via a migration carve-out.
- The classic options flow is now an informational placeholder; all
  configuration moved to sub-items.
- **Calendar styling** — events are larger, rounder and friendlier on
  a wall-mounted tablet. Event font size is view-scoped via a
  `--fb-event-font` CSS variable (Day ~1.05em → 2 weeks ~0.82em, with
  a small bump on screens ≥ 900px). All-day bars grew to 22px tall
  with 9px rounded corners and the multi-member gradient angle was
  softened from 135° to 120°. Event text auto-picks dark or light
  foreground from the background luminance (WCAG-aware) so pastel
  member colors stay readable without forcing white text.
- Slightly larger secondary text and rounder corners (16 → 20px) on
  the chores, progress and countdown cards.
- **View options reworked** — removed `tomorrow` and `today_tomorrow`;
  added `2_days` (Vandaag + 1) and `3_days` (Vandaag + 2). Restored
  states migrate automatically (`tomorrow → today`,
  `today_tomorrow → 2_days`, `Vandaag + Morgen → 2_days`).
- View chip labels are larger and bolder (~0.95rem / 600) on
  `familyboard-view-card` so they stay legible on a wall-mounted
  tablet.
- **Trash colors** — calendar card honors the per-event color encoded
  in the `[FB:trash=…;color=…]` description marker, so each trash type
  renders in its configured `trash[].color` straight from
  `configuration.yaml`. The default color was simplified to a single
  pastel grey (`#B8B8B8`); override per type via `trash[].color`.

### Fixed
- Locked the per-member progress logic for shared chores with a new
  test (`tests/test_progress.py`): completing a shared chore now has
  guardrails ensuring it credits *every* member listed on the chore.
  No code change — the existing fan-out already does this; the test
  prevents future regressions.

### Deprecated
- Top-level `meal_calendar:` and `meal_planner:` YAML keys still work
  but emit a deprecation warning. Migrate to the `meals:` block.

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

