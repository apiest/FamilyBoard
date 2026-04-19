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
  title: "FamilyBoard",
  path: "familyboard",
  icon: "mdi:home-heart",
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
    alignment: "center",
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

function _calendarCard(cfg, members) {
  const entities = members.map((m) => `calendar.familyboard_${m.name.toLowerCase()}`);
  const colors = {};
  const names = {};
  for (const m of members) {
    const eid = `calendar.familyboard_${m.name.toLowerCase()}`;
    colors[eid] = m.color || "#4A90D9";
    names[eid] = m.name;
  }
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
  };
}

function _choresCardForMember(cfg, member) {
  return {
    type: "custom:familyboard-chores-card",
    entity: cfg.chores_entity,
    member: member.name,
    filter_entity: cfg.filter_entity,
    view_entity: cfg.view_entity,
    members_entity: cfg.members_entity,
  };
}

function _allChoresCard(cfg) {
  return {
    type: "custom:familyboard-chores-card",
    entity: cfg.chores_entity,
    filter_entity: cfg.filter_entity,
    view_entity: cfg.view_entity,
    members_entity: cfg.members_entity,
  };
}

function _progressCard(cfg) {
  return {
    type: "custom:familyboard-progress-card",
    entity: cfg.progress_entity,
  };
}

class FamilyBoardDashboardStrategy extends HTMLElement {
  static async generate(strategyConfig, hass) {
    const cfg = _resolveConfig(strategyConfig);
    const members = _members(hass, cfg.members_entity);

    const sections = [];

    // 1. Top section: filter chips + view chips
    sections.push({
      type: "grid",
      cards: [_filterCard(cfg), _viewChips(cfg)],
    });

    // 2. Calendar (full-width)
    if (cfg.show_calendar) {
      sections.push({
        type: "grid",
        cards: [_calendarCard(cfg, members)],
      });
    }

    // 3. Progress
    if (cfg.show_progress) {
      sections.push({
        type: "grid",
        cards: [_progressCard(cfg)],
      });
    }

    // 4. Per-member chores
    if (cfg.show_chores) {
      if (members.length === 0) {
        sections.push({
          type: "grid",
          cards: [_allChoresCard(cfg)],
        });
      } else {
        for (const m of members) {
          sections.push({
            type: "grid",
            cards: [
              {
                type: "markdown",
                content: `## ${m.name}`,
              },
              _choresCardForMember(cfg, m),
            ],
          });
        }
      }
    }

    return {
      title: cfg.title,
      views: [
        {
          type: "sections",
          title: cfg.title,
          path: cfg.path,
          icon: cfg.icon,
          max_columns: 2,
          sections,
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
