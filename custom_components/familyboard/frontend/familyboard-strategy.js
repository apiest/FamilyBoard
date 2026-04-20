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

function _filterCard(cfg) {
  return {
    type: "custom:familyboard-filter-card",
    filter_entity: cfg.filter_entity,
    members_entity: cfg.members_entity,
  };
}

function _viewChips(cfg) {
  const opts = [
    ["Vandaag", "mdi:calendar-today"],
    ["Morgen", "mdi:calendar-arrow-right"],
    ["Week", "mdi:calendar-week"],
    ["2 Weken", "mdi:calendar-range"],
    ["Maand", "mdi:calendar-month"],
  ];
  return {
    type: "custom:mushroom-chips-card",
    grid_options: { columns: 12, rows: 1 },
    chips: opts.map(([opt, icon]) => ({
      type: "template",
      icon,
      content: opt,
      icon_color: `{{ 'amber' if is_state('${cfg.view_entity}', '${opt}') else 'grey' }}`,
      tap_action: {
        action: "perform-action",
        perform_action: "select.select_option",
        target: { entity_id: cfg.view_entity },
        data: { option: opt },
      },
    })),
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
  return {
    type: "custom:familyboard-filter-card",
    filter_entity: cfg.filter_entity,
    members_entity: cfg.members_entity,
    show_alles: true,
    extra_chips: [],
    grid_options: { columns: 10, rows: 1 },
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

function _agendaCard(cfg, members) {
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
    entities,
    colors,
    names,
    filter_map,
    grid_options: { columns: "full", rows: 16 },
  };
}

function _lijstCard(cfg, members) {
  // Build the JS literal for the CALENDARS array used by config-template-card.
  const calConsts = members
    .map(
      (m) =>
        `const ${_slug(m.name)} = {entity:'${_calId(m.name)}', color:'${m.color || "#4A90D9"}', name:'${m.name}'};`,
    )
    .join("\n  ");
  const trashConst = `const trash = {entity:'calendar.familyboard_trash', color:'#888888', name:'Trash'};`;
  const branches = members
    .map(
      (m) =>
        `if (f === '${m.name}') return [${_slug(m.name)}, trash];`,
    )
    .join("\n  ");
  const allList = members.map((m) => _slug(m.name)).concat(["trash"]).join(", ");
  const calendarsExpr = `(() => {
    const f = states['${cfg.filter_entity}'].state;
    ${trashConst}
    ${calConsts}
    ${branches}
    return [${allList}];
  })()`;
  return {
    type: "conditional",
    conditions: [{ entity: cfg.layout_entity, state: "Lijst" }],
    card: {
      type: "custom:config-template-card",
      entities: [cfg.filter_entity, cfg.view_entity],
      variables: {
        FILTER_CAL: `states['${cfg.filter_entity}'].state`,
        CALENDARS: calendarsExpr,
        VIEW: `states['${cfg.view_entity}'].state`,
        DAYS: `(() => {
            const v = states['${cfg.view_entity}'].state;
            if (v === 'Vandaag') return 1;
            if (v === 'Morgen') return 2;
            if (v === 'Week') return 7;
            if (v === '2 Weken') return 14;
            return 'month';
          })()`,
        STARTDAY: `(() => {
            const v = states['${cfg.view_entity}'].state;
            if (v === 'Vandaag') return 'today';
            if (v === 'Morgen') return 'tomorrow';
            if (v === 'Week') return 'monday';
            if (v === 'Maand') return 'monday';
            return 'today';
          })()`,
        COMPACT: `(() => {
            const v = states['${cfg.view_entity}'].state;
            return v === 'Maand';
          })()`,
      },
      card: {
        type: "custom:week-planner-card",
        days: "${DAYS}",
        startingDay: "${STARTDAY}",
        compact: "${COMPACT}",
        locale: "nl",
        noCardBackground: false,
        showLocation: false,
        showNavigation: true,
        updateInterval: 60,
        hidePastEvents: false,
        showWeekDayText: false,
        combineSimilarEvents: true,
        texts: {
          today: "Vandaag",
          tomorrow: "Morgen",
          noEvents: "Geen afspraken",
          fullDay: "Hele dag",
        },
        calendars: "${CALENDARS}",
        card_mod: { style: "ha-card { font-size: 1.1em; }\n" },
      },
    },
    grid_options: { columns: "full", rows: "auto" },
  };
}

function _todayPerMemberSection(cfg, members) {
  const cards = [{ type: "heading", heading: "⏰ Vandaag", heading_style: "title" }];
  // "Alles" branch (all calendars)
  cards.push({
    type: "conditional",
    conditions: [{ entity: cfg.filter_entity, state: "Alles" }],
    card: {
      type: "custom:atomic-calendar-revive",
      name: " ",
      enableModeChange: false,
      defaultMode: "Event",
      maxDaysToShow: 1,
      maxEventCount: 10,
      showMonth: false,
      showWeekDay: true,
      showDate: true,
      showCurrentEventLine: true,
      dimFinishedEvents: true,
      showCalendarName: true,
      showRelativeTime: true,
      eventCalNameColor: true,
      calShowDescription: false,
      showNoEventsForToday: true,
      noEventsForTodayText: "Geen afspraken vandaag 🎉",
      entities: [
        { entity: "calendar.familyboard_alles", color: "#666666", name: "Familie" },
      ],
      card_mod: { style: "ha-card { font-size: 1.2em; }\n" },
    },
  });
  for (const m of members) {
    cards.push({
      type: "conditional",
      conditions: [{ entity: cfg.filter_entity, state: m.name }],
      card: {
        type: "custom:atomic-calendar-revive",
        name: " ",
        enableModeChange: false,
        defaultMode: "Event",
        maxDaysToShow: 1,
        maxEventCount: 10,
        showMonth: false,
        showWeekDay: true,
        showDate: true,
        showCurrentEventLine: true,
        dimFinishedEvents: true,
        showCalendarName: false,
        showRelativeTime: true,
        eventCalNameColor: true,
        calShowDescription: false,
        showNoEventsForToday: true,
        noEventsForTodayText: `Geen afspraken vandaag voor ${m.name}`,
        entities: [
          { entity: _calId(m.name), color: m.color || "#4A90D9", name: m.name },
        ],
        card_mod: { style: "ha-card { font-size: 1.2em; }\n" },
      },
    });
  }
  return { type: "grid", column_span: 1, cards };
}

function _sideStackSection(cfg) {
  const stack = [];
  if (cfg.show_progress) {
    stack.push({
      type: "custom:familyboard-progress-card",
      entity: cfg.progress_entity,
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

    // Main section (column_span 3): chips + Agenda calendar
    const mainCards = [
      _filterCardSized(cfg),
      _layoutChips(cfg),
      _viewChips(cfg),
      _actionChips(),
    ];
    if (cfg.show_calendar) mainCards.push(_agendaCard(cfg, members));
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

console.info(
  "%c FAMILYBOARD-STRATEGY %c v1.0 ",
  "color: white; background: #4A90D9; font-weight: 700;",
  "color: #4A90D9; background: white; font-weight: 700;"
);
