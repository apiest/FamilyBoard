# Copilot instructions — FamilyBoard

Home Assistant custom integration (`custom_components/familyboard/`) plus a set
of vanilla-JS Lovelace cards (`custom_components/familyboard/frontend/`). No
frontend build step. Target HA: 2026.4+.

## Architecture rules

- **Native HA platforms only.** Never introduce `input_boolean`, `input_text`,
  `input_select`, `input_datetime`, etc. All UI state lives on FamilyBoard's
  own `select` / `text` / `switch` / `datetime` entities.
- **Hardcoded entity IDs** are defined in `__init__.py` and consumed by
  `dashboards/familyboard.yaml`. If you rename one, update both.
- All stateful `select` / `text` / `switch` / `datetime` classes use
  `RestoreEntity` for persistence across restarts.
- Coordinator-driven refresh; per-tick housekeeping (e.g. trash chore
  auto-completion) runs on coordinator refresh, not separate timers.
- **Options-flow ↔ YAML import contract.** YAML is re-imported on every HA
  start via `async_step_import` → `_normalize_options`. Any new options-flow
  key (set only via the UI) **must** be either listed in `_normalize_options`
  or carried over from the existing entry's options, otherwise it gets wiped
  on the next restart. When adding a new options key, update both
  `schemas.OPTIONS_SCHEMA` and `_normalize_options` (the `existing=` merge
  branch) together.

## Config schema (HA `configuration.yaml`)

```yaml
familyboard:
  members:
    - name: Person_1
      color: "#4A90D9"
      calendar: calendar.person_1
      calendar_label: Personal
      chores: [todo.person_1, todo.person_1_extra]   # replaces legacy `todo:`
      extra_calendars:
        - entity: calendar.person_1_work
          label: Work
  shared_chores:
    - entity: todo.trash
      members: [Person_1, Person_2]
      type: trash                          # triggers TrashChoreManager
      name: Trash
    - entity: todo.groceries
      members: [Person_1, Person_2]
      name: Groceries
```

`chores:` replaces the old `todo:` key. `shared_chores[]` items appear for all
listed members. `type: trash` opts the entry into auto-creation from trash
sensors.

## Key modules

- `__init__.py` — coordinator, hardcoded entity IDs, platform setup.
- `calendar.py` — `FamilyBoardAllesCalendar` cross-member dedup; multi-member
  events get `[FB:members=A,B;colors=#xxx,#yyy]` (alphabetical) in the
  description so the frontend can render multi-color borders.
- `trash.py` — `TrashChoreManager`. Creates 2 chores per trash type (bins at
  21:00 the day before, kliko at 07:00 on collection day). Dedup via
  `.storage/familyboard_trash_chores`. Auto-completes after collection date.
- `reminder.py` — interactive snooze flow over `mobile_app` actionable
  notifications; persists pending reminders across restarts.
- `sensor.py` — `familyboard_chores`, `familyboard_progress`, `familyboard_members`.
- `frontend/familyboard-strategy.js` — dashboard strategy that wires the cards.

## Frontend cards

Vanilla JS LitElement components in `custom_components/familyboard/frontend/`.
Registered automatically through the Lovelace resources API — no manual
resource URL bookkeeping. **Always deploy the JS file before restarting HA**;
the SW caches 404s, which produces "Custom element doesn't exist" errors that
survive cache-busting hashes.

## Testing

- `pytest` with fixtures in `tests/conftest.py`.
- Test deps: `requirements_test.txt`.
- Run: `pytest` from repo root.

### Manual / live testing — use the dev container

When verifying new functionality against a real HA instance, use the
repo's dev container instead of deploying to the production Pi.

- `.devcontainer.json` + `scripts/setup` install
  `requirements-dev.txt` (HA + ruff + pytest).
- `scripts/develop` boots HA on <http://localhost:8123> with this
  repo's `custom_components/familyboard` on `PYTHONPATH` (no bind
  mounts, no symlinks).
- HA config lives in `<repo>/config/`; `config/.storage/` is
  git-ignored and persists onboarding + UI-created entries across
  rebuilds.
- First boot: create owner → add Local Calendar (`Dev A`, `Dev B`)
  and Local To-do (`Dev A`, `Dev B`, `Trash`) via the UI → add the
  **FamilyBoard** integration and wire the members through the
  options flow. End-user flow only — no helper YAML.
- Iteration: Python edits → restart HA from the UI; JS edits →
  hard-reload (`Ctrl+Shift+R`) and tick *Bypass for network* in
  DevTools → Application → Service Workers if a card goes missing.

When you add or change user-visible behavior, walk through the
relevant UI flow in this dev HA before considering the task done.

### Files to keep in sync when behavior changes

If a change affects how a contributor sets up or runs the dev HA,
update **all** of these together:

- `.devcontainer.json` — extensions, features, `postCreateCommand`.
- `scripts/setup` / `scripts/develop` / `scripts/lint`.
- `requirements-dev.txt` — HA and tooling pins.
- `config/configuration.yaml` — bootstrap config (kept minimal; no
  `familyboard:` block, no stub entities).
- `README.md` *Development → Dev container* section.
- This file (`Manual / live testing` above).
## Deploy

```bash
scp custom_components/familyboard/*.py \
    custom_components/familyboard/frontend/*.js \
    root@10.10.1.16:./hass-config/custom_components/familyboard/
docker -H ssh://root@10.10.1.16 restart homeassistant   # or restart on host
```

## Documentation hygiene

- **README.md** — keep in sync whenever user-visible behavior changes.
  Specifically update the *Features* list, *Installation* section, and any
  config example when the schema changes.
- **CHANGELOG.md** — append every user-visible change under `## [Unreleased]`
  using [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) sections:
  `Added`, `Changed`, `Fixed`, `Removed`, `Deprecated`, `Security`.
  Internal-only refactors and test-only changes do not need an entry.
- **Releasing** — bump `version` in
  `custom_components/familyboard/manifest.json` (SemVer) and rename the
  `[Unreleased]` block to `## [x.y.z] - YYYY-MM-DD`. Add a fresh empty
  `## [Unreleased]` above it.
- **Do not create new markdown files to "document changes"** unless the user
  asks. `plans/` is reserved for explicit planning docs requested by the user.

## Don'ts

- No `input_*` helpers — ever.
- Don't rename hardcoded entity IDs without updating `dashboards/familyboard.yaml`.
- Don't introduce a frontend build step; cards must remain plain JS deployable
  via `scp`.
- Don't deploy by restarting HA before copying files (SW caches 404s).

## Code style — follow Home Assistant core conventions

**This is enforced by CI.** `ruff check` and `ruff format --check` run on every
push (see [`pyproject.toml`](pyproject.toml) `[tool.ruff]` for the full rule
set, mirroring HA core).

- **PEP 257 docstrings** on every module, class and public function (one-line
  imperative summary; expand if behavior isn't obvious from the signature).
  Enforced by Ruff's `D` rules.
- **Type hints** on all function signatures (parameters + return). Use
  `from __future__ import annotations` and modern syntax (`list[str]`,
  `str | None`).
- Follow the rest of the [HA style guide](https://developers.home-assistant.io/docs/development_guidelines/):
  Ruff/Black-compatible formatting, snake_case, async-first, no blocking I/O on
  the event loop, prefer `_LOGGER` over `print`.
- When editing existing code that lacks docstrings/types, add them as part of
  the change rather than leaving the file inconsistent.
- Before committing, run `ruff check --fix custom_components/familyboard tests`
  and `ruff format custom_components/familyboard tests` locally.
