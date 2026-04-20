# FamilyBoard

[![hacs][hacs-badge]][hacs-url]
[![hassfest][hassfest-badge]][hassfest-url]

Family dashboard integration for Home Assistant. Consolidates calendar
views, chore tracking, trash collection and notification reminders into
a unified family dashboard with reusable Lovelace cards.

## Features

- **Per-member calendar proxies** — primary + extra calendars, Google Tasks filtered out automatically.
- **Cross-member "Alles" calendar** — deduplicated event stream with multi-member markers (one event, multiple colored borders).
- **Trash collection calendar** — surfaces configured `sensor.*` collection dates as all-day events, optionally with auto-generated chores.
- **Chores sensor** — combined per-member list of `todo.*` items, sorted overdue → upcoming → no-date, optionally cross-matched with calendar tasks for start/end times.
- **Per-member progress sensor** — daily completion tracking with color rings.
- **Interactive snooze reminders** — actionable mobile_app notifications scheduled at task start time, with persistence across HA restarts and away-aware delivery.
- **Custom Lovelace cards** — composable building blocks: `chores`, `calendar`, `filter`, `progress`. Each takes its own config; users can mix them into any dashboard.
- **Add-event form entities** — built-in `select`, `text`, `switch` and `datetime` entities power a "create event" form with cascading member → calendar pickers.

## Installation

### HACS (recommended)

1. In HACS, choose **Integrations → ⋮ → Custom repositories** and add `https://github.com/apiest/FamilyBoard` as an _Integration_.
2. Search for **FamilyBoard** in HACS and install.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → FamilyBoard** and configure members, trash and shared calendars/chores via the UI.

### Manual

1. Copy `custom_components/familyboard/` into your HA config dir.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services**.

The integration registers its Lovelace card resources via the Lovelace
resources API — no manual URL bookkeeping required.

### YAML alternative

YAML configuration is still supported as a bootstrap: any `familyboard:`
block in `configuration.yaml` is imported into the config entry on first
start and refreshed on subsequent restarts. Edits made through the
options flow take precedence until the YAML changes again.

## Configuration

### Full example

```yaml
familyboard:
  members:
    - name: Person_1
      color: "#4A90D9"
      calendar: calendar.person_1
      calendar_label: Personal
      calendar_default_summary: ""
      calendar_default_description: ""
      person: person.person_1
      notify: mobile_app_person_1
      chores:
        - todo.person_1
        - todo.person_1_tasks
      extra_calendars:
        - entity: calendar.person_1_work
          label: Work
          default_summary: ""
          default_description: ""
    - name: Person_2
      color: "#27AE60"
      calendar: calendar.person_2
      person: person.person_2
      notify: mobile_app_person_2
      chores:
        - todo.person_2
  trash:
    - type: rest
      sensor: sensor.trash_rest
      label: Restafval
      color: "#555555"
      emoji: "🗑️"
    - type: gft
      sensor: sensor.trash_gft
  shared_calendars:
    - entity: calendar.shared
      members: [Person_1, Person_2]
      name: Shared
      color: "#9B59B6"
  shared_chores:
    - entity: todo.trash
      members: [Person_1, Person_2]
      type: trash
      name: Trash
    - entity: todo.groceries
      members: [Person_1, Person_2]
      name: Groceries
  meal_calendar: calendar.meals
```

### Member options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `name` | yes | — | Display name |
| `calendar` | yes | — | Primary calendar entity_id |
| `calendar_label` | no | `<name> privé` | Label shown in calendar picker |
| `calendar_default_summary` | no | — | Fallback summary for events without one |
| `calendar_default_description` | no | — | Fallback description for events without one |
| `color` | no | `#4A90D9` | Member color (hex) |
| `person` | no | — | `person.*` entity for presence + avatar |
| `notify` | no | — | `mobile_app_*` notify target for reminders |
| `chores` | no | `[]` | List of `todo.*` entity_ids |
| `extra_calendars` | no | `[]` | Additional calendars (see below) |

### Extra calendar options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `entity` | yes | — | Calendar entity_id |
| `label` | yes | — | Display label in pickers |
| `default_summary` | no | — | Fallback summary |
| `default_description` | no | — | Fallback description |

### Trash options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `type` | yes | — | Trash type identifier (`rest`, `paper`, `gft`, `pmd`, …) |
| `sensor` | yes | — | Sensor entity with the next collection date as state |
| `label` | no | from sensor | Display label |
| `color` | no | per-type default | Color (hex) |
| `emoji` | no | per-type default | Emoji prefix |

### Shared calendar options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `entity` | yes | — | Calendar entity_id |
| `members` | yes | — | List of member names |
| `name` | no | — | Display name |
| `color` | no | — | Color (hex) |

### Shared chore options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `entity` | yes | — | `todo.*` entity_id |
| `members` | yes | — | List of member names |
| `type` | no | — | `trash` enables auto-creation from configured trash sensors |
| `name` | no | — | Display name |
| `color` | no | — | Color (hex) |

## Entities created

### Calendars

| Entity | Description |
|--------|-------------|
| `calendar.familyboard_<name>` | Per-member proxy (Google Tasks filtered out) |
| `calendar.familyboard_alles` | Cross-member deduplicated view with member markers |
| `calendar.familyboard_trash` | Trash collection dates from configured sensors |

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.familyboard_chores` | Combined chore list (count + items attribute) |
| `sensor.familyboard_members` | Member metadata for cards |
| `sensor.familyboard_progress` | Per-member daily completion progress |
| `sensor.familyboard_compliment` | Time-of-day greeting |

### Controls (form / filter)

| Entity | Description |
|--------|-------------|
| `select.familyboard_calendar` | Member/Alles filter chip |
| `select.familyboard_view` | Time window (Vandaag/Morgen/Week/2 Weken/Maand) |
| `select.familyboard_layout` | Layout mode (Lijst/Agenda) |
| `select.familyboard_event_member` | Add-event: member picker |
| `select.familyboard_event_calendar` | Add-event: calendar picker (cascades from member) |
| `text.familyboard_event_title` | Add-event: title input |
| `switch.familyboard_event_all_day` | Add-event: all-day toggle |
| `switch.familyboard_show_reminders` | Show/hide reminder notifications globally |
| `datetime.familyboard_event_start` | Add-event: start datetime |
| `datetime.familyboard_event_end` | Add-event: end datetime |
| `datetime.familyboard_day_start` | Add-event: all-day start |
| `datetime.familyboard_day_end` | Add-event: all-day end |

## Service actions

| Service | Description | Fields |
|---------|-------------|--------|
| `familyboard.add_event` | Create event from form entities | — (reads entity states) |
| `familyboard.snooze_test` | Test-fire a reminder | `uid` |
| `familyboard.cancel_reminder` | Cancel an active reminder | `uid` |

## Lovelace cards

Each card is a self-contained building block — drop it in any view, any
layout, alongside core or third-party cards.

| Card type | Required config | Description |
|-----------|-----------------|-------------|
| `custom:familyboard-chores-card` | `entity`, `filter_entity`, `view_entity`, `members_entity` | Sorted chore list with member filter |
| `custom:familyboard-calendar-card` | `members_entity`, calendar entity_ids | Calendar timeline view |
| `custom:familyboard-filter-card` | `filter_entity`, `members_entity` | Member filter chips |
| `custom:familyboard-progress-card` | `entity` | Per-member progress rings |

### Example chores card

```yaml
type: custom:familyboard-chores-card
entity: sensor.familyboard_chores
filter_entity: select.familyboard_calendar
view_entity: select.familyboard_view
members_entity: sensor.familyboard_members
```

## Dashboard options

There are three ways to use FamilyBoard in your dashboards:

1. **Compose your own** — add the cards listed above into any dashboard, any view, any layout. The cards are independent; mix freely with core/HACS cards.
2. **Static template** — `dashboards/familyboard.yaml` in this repo provides a curated full layout. Reference it from `configuration.yaml` under `lovelace.dashboards`.
3. **Dashboard strategy** — `strategy: type: custom:familyboard` auto-generates a sections-view dashboard from the current members, chores and calendars sensors. Add or remove a member and the dashboard updates automatically. "Take Control" in the UI converts the generated layout back into editable YAML for further tweaking.

### Strategy example

```yaml
# A whole dashboard generated by the strategy:
strategy:
  type: custom:familyboard
  # All keys below are optional with sensible defaults
  show_calendar: true
  show_chores: true
  show_progress: true
  members_entity: sensor.familyboard_members
  chores_entity: sensor.familyboard_chores
  filter_entity: select.familyboard_calendar
  view_entity: select.familyboard_view
```

You can also use it as a **view strategy** (one view inside an existing dashboard):

```yaml
views:
  - strategy:
      type: custom:familyboard
    title: Family
    path: family
```

## Optional theming

`themes/familyboard.yaml` provides a dark Skylight-inspired theme that
the cards' default CSS variables target. Install by referencing the
`themes/` folder from your `configuration.yaml`:

```yaml
frontend:
  themes: !include_dir_merge_named themes
```

Then select **FamilyBoard** in your user profile theme picker. The theme
is fully optional — the cards work with any theme.

## Dependencies

Required HACS frontend resources (the integration warns if missing):

- [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)

## Development

- HA target: 2026.4.x (also works on 2025.1+).
- Single config entry; full UI options flow + YAML bootstrap.
- Local testing: `pip install -r requirements_test.txt && pytest`.
- CI: GitHub Actions runs hassfest, HACS validation and pytest on every push.

### Dev container (recommended for manual testing)

Run a real Home Assistant instance against this repo without touching
your production HA.

**Prerequisites:** Docker, VS Code, and the
[Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
extension.

1. Open the repo in VS Code → Command Palette → **Dev Containers:
   Reopen in Container**. First build runs `scripts/setup`, which
   installs `requirements-dev.txt` (Home Assistant + ruff + pytest
   stack).
2. In the integrated terminal: `scripts/develop`. HA starts on
   <http://localhost:8123> with this repo's
   `custom_components/familyboard` on `PYTHONPATH` (no bind mounts or
   symlinks). VS Code users can also hit F5 → *Home Assistant: dev
   (scripts/develop)* to launch under debugpy.
3. First boot — exercise the real end-user flow:
   1. Create the owner account.
   2. **Settings → Devices & services → Add integration** and add:
      - Local Calendar × 2 → `Dev A`, `Dev B`
      - Local To-do × 3 → `Dev A`, `Dev B`, `Trash`
   3. Add **FamilyBoard**, then use the options flow to wire two
      members (Dev_A, Dev_B) to the entities above and add `todo.trash`
      as a shared chore (`type: trash`).
4. `config/.storage/` (git-ignored) persists this setup across
   container rebuilds, so it's a one-time exercise.

Iteration loop:

- Python edits → restart HA from **Developer Tools → YAML → Restart**
  (or Ctrl+C in the `scripts/develop` terminal and re-run).
- Frontend (`custom_components/familyboard/frontend/*.js`) edits →
  hard-reload the browser (Ctrl+Shift+R). If a card "doesn't exist"
  after editing, open DevTools → Application → Service Workers → tick
  *Bypass for network*.
- Format + lint: `scripts/lint`.
- Tests: `pytest`.

Without Docker, the same `scripts/setup` and `scripts/develop` work in
a host virtualenv.

## Acknowledgements

This project was developed with substantial help from AI coding assistants
(GitHub Copilot / Claude). All code has been reviewed, tested against Home
Assistant 2026.4.x and is maintained by a human — but if you spot a quirk that
smells like an LLM hallucination, please open an issue.

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://github.com/hacs/integration
[hassfest-badge]: https://github.com/apiest/FamilyBoard/actions/workflows/hassfest.yml/badge.svg
[hassfest-url]: https://github.com/apiest/FamilyBoard/actions/workflows/hassfest.yml
