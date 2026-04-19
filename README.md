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
4. Add YAML configuration (see below) and restart again.

### Manual

1. Copy `custom_components/familyboard/` into your HA config dir.
2. Add the YAML configuration.
3. Restart Home Assistant.

The integration auto-creates a config entry on first start and registers
its Lovelace card resources via the Lovelace resources API — no manual
URL bookkeeping required.

## Configuration

### Full example

```yaml
familyboard:
  members:
    - name: Berry
      color: "#4A90D9"
      calendar: calendar.berry
      calendar_label: Persoonlijk
      calendar_default_summary: ""
      calendar_default_description: ""
      person: person.berry
      notify: mobile_app_berry
      chores:
        - todo.berry
        - todo.berry_taken
      extra_calendars:
        - entity: calendar.berry_werk
          label: Werk
          default_summary: ""
          default_description: ""
    - name: Sylvia
      color: "#27AE60"
      calendar: calendar.sylvia
      person: person.sylvia
      notify: mobile_app_sylvia
      chores:
        - todo.sylvia
  trash:
    - type: rest
      sensor: sensor.trash_rest
      label: Restafval
      color: "#555555"
      emoji: "🗑️"
    - type: gft
      sensor: sensor.trash_gft
  shared_calendars:
    - entity: calendar.gezamenlijk
      members: [Berry, Sylvia]
      name: Gezamenlijk
      color: "#9B59B6"
  shared_chores:
    - entity: todo.trash
      members: [Berry, Sylvia]
      type: trash
      name: Afval
    - entity: todo.boodschappen
      members: [Berry, Sylvia]
      name: Boodschappen
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
3. **Dashboard strategy** _(Phase 11, planned)_ — `strategy: type: custom:familyboard` will auto-generate the curated layout from current entities; "Take Control" converts it back into editable YAML.

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
- Single config entry, YAML-driven; full UI options flow is planned (Phase 8).
- Local testing: `python -m pytest` once tests are added (Phase 9).

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://github.com/hacs/integration
[hassfest-badge]: https://github.com/apiest/FamilyBoard/actions/workflows/hassfest.yml/badge.svg
[hassfest-url]: https://github.com/apiest/FamilyBoard/actions/workflows/hassfest.yml
