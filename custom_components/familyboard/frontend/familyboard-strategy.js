/**
 * FamilyBoard Dashboard Strategy
 *
 * Auto-generates a sections-view dashboard from FamilyBoard's data so users
 * don't have to maintain hundreds of lines of per-member YAML.
 *
 * Usage in a Lovelace dashboard YAML:
 *   strategy:
 *     type: custom:familyboard
 *     # Optional overrides
 *     show_progress: true        # default true
 *     show_calendar: true        # default true
 *     show_chores: true          # default true
 *     members_entity: sensor.familyboard_members
 *     chores_entity: sensor.familyboard_chores
 *     filter_entity: select.familyboard_calendar
 *     view_entity: select.familyboard_view
 *     reminders_switch: switch.familyboard_show_reminders
 *
 * The strategy reads `sensor.familyboard_members` (attributes.members) to
 * discover members and their colors.
 */

const DEFAULTS = {
  members_entity: "sensor.familyboard_members",
  chores_entity: "sensor.familyboard_chores",
  progress_entity: "sensor.familyboard_progress",
  filter_entity: "select.familyboard_calendar",
  view_entity: "select.familyboard_view",
  layout_entity: "select.familyboard_layout",
  reminders_switch: "switch.familyboard_show_reminders",
  show_calendar: true,
  show_chores: true,
  show_progress: true,
  show_countdown: true,
  countdown_label_entity: "text.familyboard_countdown_label",
  countdown_date_entity: "datetime.familyboard_countdown_date",
  title: "Family Board",
  path: "familyboard",
  icon: "mdi:calendar-multiple",
};

function _resolveConfig(userConfig) {
  return { ...DEFAULTS, ...(userConfig || {}) };
}

function _members(hass, entity) {
  const s = hass.states[entity];
  if (!s || !s.attributes || !Array.isArray(s.attributes.members)) return [];
  return s.attributes.members;
}

function _viewChips(cfg) {
  // Delegates label rendering + i18n to the dedicated view card.
  return {
    type: "custom:familyboard-view-card",
    entity: cfg.view_entity,
    grid_options: { columns: 12, rows: 1 },
  };
}

function _layoutChips(cfg) {
  const chips = [
    {
      type: "template",
      icon: `{{ 'mdi:bell' if is_state('${cfg.reminders_switch}', 'on') else 'mdi:bell-off' }}`,
      icon_color: `{{ 'amber' if is_state('${cfg.reminders_switch}', 'on') else 'grey' }}`,
      content: "Herinneringen",
      tap_action: {
        action: "perform-action",
        perform_action: "switch.toggle",
        target: { entity_id: cfg.reminders_switch },
      },
    },
  ];
  return {
    type: "custom:mushroom-chips-card",
    grid_options: { columns: 8, rows: 1 },
    chips,
  };
}

function _filterCardSized(cfg) {
  // Deprecated in the default dashboard — the progress card now exposes
  // built-in filter chips (glow on the selected member). Kept here so a
  // user override that explicitly invokes the helper still works.
  return {
    type: "custom:familyboard-filter-card",
    filter_entity: cfg.filter_entity,
    members_entity: cfg.members_entity,
    show_alles: true,
    extra_chips: [],
    grid_options: { columns: 10, rows: 1 },
  };
}

function _progressCardMain(cfg) {
  return {
    type: "custom:familyboard-progress-card",
    entity: cfg.progress_entity,
    filter_entity: cfg.filter_entity,
    selectable: true,
    grid_options: { columns: "full", rows: 2 },
  };
}

function _slug(name) {
  // Mirror Home Assistant's slugify: lowercase, replace any run of
  // non-alphanumeric characters with `_`, strip leading/trailing `_`.
  return String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function _calId(name) {
  return `calendar.familyboard_${_slug(name)}`;
}

function _actionChips() {
  return {
    type: "custom:mushroom-chips-card",
    alignment: "end",
    grid_options: { columns: 5, rows: 1 },
    chips: [
      {
        type: "template",
        icon: "mdi:calendar-plus",
        icon_color: "cyan",
        content: "Afspraak",
        tap_action: { action: "navigate", navigation_path: "#addcalendarevent" },
      },
    ],
  };
}

function _categoryChips(hass) {
  if (!hass) return null;
  const switches = Object.keys(hass.states || {})
    .filter((id) => id.startsWith("switch.familyboard_category_"))
    .sort();
  if (switches.length < 2) return null;
  return {
    type: "custom:mushroom-chips-card",
    alignment: "start",
    grid_options: { columns: "full", rows: 1 },
    chips: switches.map((swid) => ({
      type: "entity",
      entity: swid,
      icon: "mdi:calendar-filter",
      content_info: "name",
      tap_action: {
        action: "call-service",
        service: "switch.toggle",
        target: { entity_id: swid },
      },
    })),
  };
}

function _agendaCard(cfg, members, hass) {
  const entities = members.map((m) => _calId(m.name));
  const colors = {};
  const names = {};
  const filter_map = {};
  for (const m of members) {
    const eid = _calId(m.name);
    colors[eid] = m.color || "#4A90D9";
    names[eid] = m.name;
    filter_map[m.name] = [eid, "calendar.familyboard_trash"];
  }
  // Trash calendar is always registered (empty when no sensors configured).
  entities.push("calendar.familyboard_trash");
  colors["calendar.familyboard_trash"] = "#888888";
  names["calendar.familyboard_trash"] = "Trash";
  // Discover registered category switches so the calendar card can filter
  // events by category. Switches are created server-side, one per
  // calendar category actually in use (see switch.py).
  const category_switches = hass
    ? Object.keys(hass.states || {})
        .filter((id) => id.startsWith("switch.familyboard_category_"))
        .sort()
    : [];
  return {
    type: "custom:familyboard-calendar-card",
    view: "day",
    start_hour: 7,
    end_hour: 23,
    slot_minutes: 30,
    row_height: 24,
    locale: "nl",
    filter_entity: cfg.filter_entity,
    view_entity: cfg.view_entity,
    reminders_entity: cfg.chores_entity,
    reminders_hide_when: cfg.reminders_switch,
    category_switches,
    entities,
    colors,
    names,
    filter_map,
    grid_options: { columns: "full", rows: 16 },
  };
}

function _sideStackSection(cfg) {
  const stack = [];
  if (cfg.show_countdown !== false) {
    stack.push({
      type: "custom:familyboard-countdown-card",
      label_entity: cfg.countdown_label_entity,
      date_entity: cfg.countdown_date_entity,
    });
  }
  if (cfg.show_chores) {
    stack.push({
      type: "conditional",
      conditions: [{ entity: cfg.reminders_switch, state: "on" }],
      card: {
        type: "vertical-stack",
        cards: [
          { type: "heading", heading: "🔔 Herinneringen", heading_style: "title" },
          {
            type: "custom:familyboard-chores-card",
            entity: cfg.chores_entity,
            filter_entity: cfg.filter_entity,
            view_entity: cfg.view_entity,
          },
        ],
      },
    });
  }
  return {
    type: "grid",
    cards: stack.length ? [{ type: "vertical-stack", cards: stack }] : [],
  };
}

function _addEventSection() {
  return {
    type: "grid",
    column_span: 4,
    cards: [
      {
        type: "vertical-stack",
        cards: [
          {
            type: "custom:bubble-card",
            card_type: "pop-up",
            hash: "#addcalendarevent",
            button_type: "name",
            name: "Afspraak toevoegen",
            icon: "mdi:calendar-plus",
            show_icon: true,
            show_name: true,
          },
          {
            type: "entities",
            title: "Nieuwe afspraak",
            state_color: false,
            entities: [
              { entity: "select.familyboard_event_member", name: "Wie" },
              { entity: "select.familyboard_event_calendar", name: "Agenda" },
              { entity: "text.familyboard_event_title", name: "Titel" },
              { entity: "switch.familyboard_event_all_day", name: "Hele dag" },
            ],
          },
          {
            type: "conditional",
            conditions: [
              { entity: "switch.familyboard_event_all_day", state: "off" },
            ],
            card: {
              type: "entities",
              entities: [
                { entity: "datetime.familyboard_event_start", name: "Start" },
                { entity: "datetime.familyboard_event_end", name: "Einde" },
              ],
            },
          },
          {
            type: "conditional",
            conditions: [
              { entity: "switch.familyboard_event_all_day", state: "on" },
            ],
            card: {
              type: "entities",
              entities: [
                { entity: "datetime.familyboard_day_start", name: "Startdatum" },
                { entity: "datetime.familyboard_day_end", name: "Einddatum" },
              ],
            },
          },
          {
            type: "custom:mushroom-chips-card",
            chips: [
              {
                type: "template",
                icon: "mdi:check",
                icon_color: "green",
                content: "Toevoegen",
                tap_action: {
                  action: "perform-action",
                  perform_action: "familyboard.add_event",
                },
              },
            ],
          },
        ],
      },
    ],
  };
}

class FamilyBoardDashboardStrategy extends HTMLElement {
  static async generate(strategyConfig, hass) {
    const cfg = _resolveConfig(strategyConfig);
    const members = _members(hass, cfg.members_entity);

    // Main section (column_span 3): progress (with filter glow) + chips + Agenda calendar
    const mainCards = [];
    if (cfg.show_progress) mainCards.push(_progressCardMain(cfg));
    mainCards.push(_layoutChips(cfg));
    mainCards.push(_viewChips(cfg));
    mainCards.push(_actionChips());
    const catChips = _categoryChips(hass);
    if (catChips) mainCards.push(catChips);
    if (cfg.show_calendar) mainCards.push(_agendaCard(cfg, members, hass));
    const mainSection = { type: "grid", column_span: 3, cards: mainCards };

    const sections = [mainSection, _sideStackSection(cfg)];
    sections.push(_addEventSection());

    return {
      title: cfg.title,
      views: [
        {
          type: "sections",
          title: cfg.title,
          path: cfg.path,
          icon: cfg.icon,
          max_columns: 4,
          sections,
          badges: [],
          header: {},
          cards: [],
        },
      ],
    };
  }
}

class FamilyBoardViewStrategy extends HTMLElement {
  static async generate(strategyConfig, hass) {
    const dash = await FamilyBoardDashboardStrategy.generate(
      strategyConfig,
      hass
    );
    return dash.views[0];
  }
}

customElements.define(
  "ll-strategy-dashboard-familyboard",
  FamilyBoardDashboardStrategy
);
customElements.define(
  "ll-strategy-view-familyboard",
  FamilyBoardViewStrategy
);

const FB_VERSION = (() => {
  try {
    return new URL(import.meta.url).searchParams.get("v") || "dev";
  } catch (_e) {
    return "dev";
  }
})();

console.info(
  `%c FAMILYBOARD-STRATEGY %c v${FB_VERSION} `,
  "color: white; background: #4A90D9; font-weight: 700;",
  "color: #4A90D9; background: white; font-weight: 700;"
);
