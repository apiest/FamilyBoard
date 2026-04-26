/**
 * FamilyBoard Calendar Card
 *
 * Native time-grid calendar with day / week / 2weeks / month views.
 * Vanilla web component, fed by HA WebSocket `calendar/get_events`.
 *
 * Phase 1: Day view + skeleton (week/2weeks/month placeholder).
 *
 * Config:
 *   type: custom:familyboard-calendar-card
 *   entities:
 *     - calendar.familyboard_member_1
 *     - calendar.familyboard_member_2
 *     - calendar.familyboard_member_3
 *     - calendar.familyboard_trash
 *   colors:
 *     calendar.familyboard_member_1: "#4A90D9"
 *     calendar.familyboard_member_2: "#27AE60"
 *     calendar.familyboard_member_3: "#F39C12"
 *     calendar.familyboard_trash: "#888888"
 *   names:                                # optional pretty names
 *     calendar.familyboard_member_1: Member 1
 *   view: day                             # day | week | 2weeks | month (default: day)
 *   start_hour: 7                         # default 7
 *   end_hour: 23                          # default 23
 *   slot_minutes: 30                      # default 30
 *   row_height: 24                        # px per slot row, default 24
 *   filter_entity: select.familyboard_calendar
 *   view_entity: select.familyboard_view  # optional, syncs view from select state
 *   filter_map:                           # optional: maps filter value -> entity list
 *     Member 1: [calendar.familyboard_member_1, calendar.familyboard_trash]
 *     Member 2: [calendar.familyboard_member_2, calendar.familyboard_trash]
 *     Alles: []                           # empty = show all
 *   show_now_indicator: true
 *   show_navigation: true
 *   weather_entity: weather.xyz           # optional, badge per dayhead (Phase 4)
 *   locale: nl
 */

const DEFAULT_COLORS = ["#4A90D9", "#27AE60", "#F39C12", "#9B59B6", "#E74C3C", "#1ABC9C"];
const VIEW_NL = {
  day: "Vandaag",
  "2days": "Vandaag + Morgen",
  week: "Week",
  workweek: "Werkweek",
  "2weeks": "2 Weken",
  month: "Maand",
};
// Map stable select-state keys to internal view modes.
const VIEW_FROM_SELECT = {
  today: "day",
  tomorrow: "day",
  today_tomorrow: "2days",
  week: "week",
  work_week: "workweek",
  two_weeks: "2weeks",
  month: "month",
};
// firstWeekday string -> day index (0 = Sunday)
const FIRST_WEEKDAY_MAP = {
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
  sunday: 0,
};

class FamilyBoardCalendarCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._events = []; // merged event list for current visible range
    this._loading = false;
    this._error = null;
    this._currentStart = this._startOfDay(new Date());
    this._tickTimer = null;
    this._fetchKey = null;
    this._lastStateSig = null;
    this._lastViewState = null;
    this._lastViewState = null;
  }

  connectedCallback() {
    if (!this._tickTimer) {
      // re-render every 60s for "now" line + "Morgen" mode date roll
      this._tickTimer = setInterval(() => this._render(), 60000);
    }
  }

  disconnectedCallback() {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
      this._tickTimer = null;
    }
  }

  setConfig(config) {
    config = config || {};
    const entities = Array.isArray(config.entities)
      ? config.entities.filter((e) => typeof e === "string" && e.includes("."))
      : [];
    // shared_calendars: { 'calendar.family': {members:['Member 1','Member 2','Member 3'], color:'#...', name:'Family'}, ... }
    const sharedCalendars = (config.shared_calendars && typeof config.shared_calendars === "object")
      ? config.shared_calendars
      : {};
    // member_entities: { 'Member 1': 'calendar.familyboard_member_1', ... } — used to look up member color
    const memberEntities = (config.member_entities && typeof config.member_entities === "object")
      ? config.member_entities
      : {};
    this._config = {
      entities,
      colors: config.colors || {},
      names: config.names || {},
      view: config.view || "day",
      start_hour: this._clampInt(config.start_hour, 0, 23, 7),
      end_hour: this._clampInt(config.end_hour, 1, 24, 23),
      slot_minutes: [15, 20, 30, 60].includes(config.slot_minutes) ? config.slot_minutes : 30,
      row_height: this._clampInt(config.row_height, 12, 80, 24),
      filter_entity: config.filter_entity || null,
      view_entity: config.view_entity || null,
      filter_map: config.filter_map || null,
      shared_calendars: sharedCalendars,
      member_entities: memberEntities,
      config_entity: config.config_entity || "sensor.familyboard_members",
      reminders_entity: config.reminders_entity || null,
      reminders_hide_when: config.reminders_hide_when || null,
      show_now_indicator: config.show_now_indicator !== false,
      show_navigation: config.show_navigation !== false,
      weather_entity: config.weather_entity || null,
      weather_show_low: config.weather_show_low === true,
      locale: config.locale || "nl",
    };
    if (this._config.end_hour <= this._config.start_hour) {
      this._config.end_hour = this._config.start_hour + 1;
    }
    this._fetchKey = null;
    this._render();
  }

  set hass(hass) {
    const prev = this._hass;
    this._hass = hass;
    // detect view-entity change → reset currentStart to natural anchor
    if (this._config.view_entity) {
      const s = hass?.states?.[this._config.view_entity];
      const newView = s ? s.state : null;
      if (newView && newView !== this._lastViewState) {
        this._lastViewState = newView;
        this._anchorCurrentStartFor(newView);
      }
    }
    const sig = this._stateSignature(hass);
    if (sig !== this._lastStateSig) {
      this._lastStateSig = sig;
      this._maybeFetch();
      this._render();
    } else if (!prev) {
      this._maybeFetch();
      this._render();
    }
  }

  _anchorCurrentStartFor(viewSelectState) {
    const today = this._startOfDay(new Date());
    if (viewSelectState === "today" || viewSelectState === "today_tomorrow") {
      this._currentStart = today;
    } else if (viewSelectState === "tomorrow") {
      this._currentStart = this._addDays(today, 1);
    } else if (viewSelectState === "week" || viewSelectState === "two_weeks") {
      // snap to first weekday of current week (HA locale)
      const fw = this._firstWeekday();
      const dow = (today.getDay() - fw + 7) % 7;
      this._currentStart = this._addDays(today, -dow);
    } else if (viewSelectState === "work_week") {
      // always snap to Monday of current week
      const dow = (today.getDay() + 6) % 7; // Mon=0
      this._currentStart = this._addDays(today, -dow);
    } else if (viewSelectState === "month") {
      this._currentStart = new Date(today.getFullYear(), today.getMonth(), 1);
    }
    this._fetchKey = null;
  }

  // First day of week index (0=Sun..6=Sat) from HA user locale; fallback Monday.
  _firstWeekday() {
    const fw = this._hass?.locale?.firstWeekday;
    if (typeof fw === "number" && fw >= 0 && fw <= 6) return fw;
    if (typeof fw === "string") {
      const v = FIRST_WEEKDAY_MAP[fw.toLowerCase()];
      if (v !== undefined) return v;
    }
    return 1; // Monday default
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { rows: 6, columns: 12, min_columns: 6 };
  }

  static getStubConfig() {
    return {
      members_entity: "sensor.familyboard_members",
      view: "week",
    };
  }

  // ---------- helpers ----------

  _clampInt(v, min, max, def) {
    const n = parseInt(v, 10);
    if (Number.isNaN(n)) return def;
    return Math.max(min, Math.min(max, n));
  }

  _startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  // Parse YYYY-MM-DD as local midnight (avoid UTC drift for all-day events)
  _parseLocalDate(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return new Date(s);
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 0, 0, 0, 0);
  }

  _addDays(d, n) {
    const x = new Date(d);
    x.setDate(x.getDate() + n);
    return x;
  }

  _isSameDay(a, b) {
    return (
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate()
    );
  }

  _stateSignature(hass) {
    if (!hass) return "";
    const parts = [];
    const allEntities = new Set([
      ...(this._config.entities || []),
      ...Object.keys(this._effectiveSharedCalendars()),
    ]);
    for (const e of allEntities) {
      const s = hass.states[e];
      parts.push(`${e}:${s ? s.state + "|" + (s.last_changed || "") : "x"}`);
    }
    if (this._config.filter_entity) {
      const s = hass.states[this._config.filter_entity];
      parts.push(`f:${s ? s.state : "x"}`);
    }
    if (this._config.view_entity) {
      const s = hass.states[this._config.view_entity];
      parts.push(`v:${s ? s.state : "x"}`);
    }
    if (this._config.reminders_hide_when) {
      const s = hass.states[this._config.reminders_hide_when];
      parts.push(`rh:${s ? s.state : "x"}`);
    }
    if (this._config.reminders_entity) {
      const s = hass.states[this._config.reminders_entity];
      parts.push(`r:${s ? s.state + "|" + (s.last_changed || "") : "x"}`);
    }
    if (this._config.config_entity) {
      const s = hass.states[this._config.config_entity];
      parts.push(`cfg:${s ? s.state + "|" + (s.last_changed || "") : "x"}`);
    }
    return parts.join(";");
  }

  // Resolve shared_calendars: dashboard config wins, else from sensor attribute
  _effectiveSharedCalendars() {
    const fromCfg = this._config.shared_calendars || {};
    if (Object.keys(fromCfg).length) return fromCfg;
    const sensor = this._hass?.states?.[this._config.config_entity];
    const list = sensor?.attributes?.shared_calendars;
    if (!Array.isArray(list)) return {};
    const out = {};
    for (const sc of list) {
      if (sc && sc.entity) {
        out[sc.entity] = {
          members: sc.members || [],
          name: sc.name,
          color: sc.color,
        };
      }
    }
    return out;
  }

  // Resolve member → calendar entity (for color lookup of shared events)
  _effectiveMemberEntities() {
    const fromCfg = this._config.member_entities || {};
    if (Object.keys(fromCfg).length) return fromCfg;
    const sensor = this._hass?.states?.[this._config.config_entity];
    const list = sensor?.attributes?.members;
    if (!Array.isArray(list)) return {};
    const out = {};
    for (const m of list) {
      if (m && m.name && m.calendar) out[m.name] = m.calendar;
    }
    return out;
  }

  // Resolve member color (from sensor) for use as fallback when colors[] not set
  _effectiveMemberColors() {
    const sensor = this._hass?.states?.[this._config.config_entity];
    const list = sensor?.attributes?.members;
    if (!Array.isArray(list)) return {};
    const out = {};
    for (const m of list) {
      if (m && m.name && m.color) out[m.name] = m.color;
    }
    return out;
  }

  _activeView() {
    if (this._config.view_entity && this._hass) {
      const s = this._hass.states[this._config.view_entity];
      if (s && VIEW_FROM_SELECT[s.state]) return VIEW_FROM_SELECT[s.state];
    }
    return this._config.view;
  }

  _activeFilterValue() {
    if (!this._config.filter_entity || !this._hass) return null;
    const s = this._hass.states[this._config.filter_entity];
    return s ? s.state : null;
  }

  _activeEntities() {
    const all = this._config.entities;
    const sharedMap = this._effectiveSharedCalendars();
    const sharedKeys = Object.keys(sharedMap);
    const fv = this._activeFilterValue();
    // No filter / Alles → all personal + all shared
    if (!fv || fv === "Alles" || fv === "All") {
      return [...all, ...sharedKeys];
    }
    // Resolve personal entities from filter_map or fallback
    let personal;
    if (this._config.filter_map && this._config.filter_map[fv]) {
      const list = this._config.filter_map[fv];
      personal = (Array.isArray(list) && list.length)
        ? list.filter((e) => all.includes(e))
        : all;
    } else {
      const lf = fv.toLowerCase().replace(/\s+/g, "_");
      const matched = all.filter((e) => e.toLowerCase().endsWith("_" + lf));
      personal = matched.length ? matched : all;
    }
    // Add shared cals where filter value is in members
    const shared = sharedKeys.filter((k) => {
      const members = sharedMap[k]?.members || [];
      return members.includes(fv);
    });
    return [...personal, ...shared];
  }

  // Color for a member name, derived from member_entities → colors, else from sensor attribute
  _memberColor(memberName) {
    const memberEnts = this._effectiveMemberEntities();
    const ent = memberEnts[memberName];
    if (ent && this._config.colors[ent]) return this._config.colors[ent];
    const fromSensor = this._effectiveMemberColors()[memberName];
    if (fromSensor) return fromSensor;
    return null;
  }

  _entityColor(entityId, idx = 0) {
    if (this._config.colors[entityId]) return this._config.colors[entityId];
    const stateAttr = this._hass?.states[entityId]?.attributes?.color;
    if (stateAttr) return stateAttr;
    return DEFAULT_COLORS[idx % DEFAULT_COLORS.length];
  }

  _entityName(entityId) {
    if (this._config.names[entityId]) return this._config.names[entityId];
    const s = this._hass?.states[entityId];
    return s?.attributes?.friendly_name || entityId.split(".").pop();
  }

  // Returns [start, end] Date covering visible range for the current view
  _visibleRange() {
    const view = this._activeView();
    const start = new Date(this._currentStart);
    let end;
    if (view === "day") end = this._addDays(start, 1);
    else if (view === "2days") end = this._addDays(start, 2);
    else if (view === "workweek") end = this._addDays(start, 5);
    else if (view === "week") end = this._addDays(start, 7);
    else if (view === "2weeks") end = this._addDays(start, 14);
    else if (view === "month") {
      // month grid: align to first weekday before 1st of month, 6 weeks
      const first = new Date(start.getFullYear(), start.getMonth(), 1);
      const fw = this._firstWeekday();
      const dow = (first.getDay() - fw + 7) % 7;
      const gridStart = this._addDays(first, -dow);
      return [gridStart, this._addDays(gridStart, 42)];
    } else {
      end = this._addDays(start, 1);
    }
    return [start, end];
  }

  // ---------- data fetch ----------

  _maybeFetch() {
    if (!this._hass) return;
    const [start, end] = this._visibleRange();
    const ents = this._activeEntities();
    const key = `${start.toISOString()}|${end.toISOString()}|${ents.join(",")}`;
    if (key === this._fetchKey) return;
    this._fetchKey = key;
    this._fetchEvents(ents, start, end);
    this._maybeFetchWeather();
  }

  async _maybeFetchWeather() {
    const ent = this._config.weather_entity;
    if (!ent || !this._hass) return;
    const now = Date.now();
    if (
      this._weather &&
      this._weather.entityId === ent &&
      now - this._weather.fetchedAt < 15 * 60 * 1000
    ) {
      return;
    }
    try {
      const resp = await this._hass.callWS({
        type: "call_service",
        domain: "weather",
        service: "get_forecasts",
        service_data: { type: "daily" },
        target: { entity_id: ent },
        return_response: true,
      });
      const list = resp?.response?.[ent]?.forecast || [];
      const byDate = {};
      for (const f of list) {
        const d = new Date(f.datetime);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        byDate[key] = {
          condition: f.condition,
          temperature: f.temperature,
          templow: f.templow,
        };
      }
      this._weather = { entityId: ent, fetchedAt: now, byDate };
      this._render();
    } catch (e) {
      console.warn("familyboard-calendar-card: weather fetch failed", e);
    }
  }

  _weatherForDay(date) {
    if (!this._weather) return null;
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    return this._weather.byDate[key] || null;
  }

  _weatherIcon(condition) {
    const map = {
      "clear-night": "mdi:weather-night",
      cloudy: "mdi:weather-cloudy",
      exceptional: "mdi:alert-circle-outline",
      fog: "mdi:weather-fog",
      hail: "mdi:weather-hail",
      lightning: "mdi:weather-lightning",
      "lightning-rainy": "mdi:weather-lightning-rainy",
      partlycloudy: "mdi:weather-partly-cloudy",
      pouring: "mdi:weather-pouring",
      rainy: "mdi:weather-rainy",
      snowy: "mdi:weather-snowy",
      "snowy-rainy": "mdi:weather-snowy-rainy",
      sunny: "mdi:weather-sunny",
      windy: "mdi:weather-windy",
      "windy-variant": "mdi:weather-windy-variant",
    };
    return map[condition] || "mdi:weather-cloudy";
  }

  _weatherColor(condition) {
    const map = {
      sunny: "#fbc02d",
      "clear-night": "#90caf9",
      partlycloudy: "#fdd835",
      cloudy: "#b0bec5",
      fog: "#cfd8dc",
      hail: "#81d4fa",
      lightning: "#ffb300",
      "lightning-rainy": "#ffb300",
      pouring: "#1976d2",
      rainy: "#42a5f5",
      snowy: "#e1f5fe",
      "snowy-rainy": "#b3e5fc",
      windy: "#90a4ae",
      "windy-variant": "#90a4ae",
      exceptional: "#ef5350",
    };
    return map[condition] || "currentColor";
  }

  _renderWeather(date) {
    const f = this._weatherForDay(date);
    if (!f) return "";
    const icon = this._weatherIcon(f.condition);
    const color = this._weatherColor(f.condition);
    const high = f.temperature != null ? `${Math.round(f.temperature)}\u00b0` : "";
    if (this._config.weather_show_low && f.templow != null) {
      const low = `${Math.round(f.templow)}\u00b0`;
      return `<div class="fb-day-wx"><ha-icon icon="${icon}" style="color:${color}"></ha-icon><span class="fb-wx-temps"><span class="fb-wx-lo">${low}</span> / <span class="fb-wx-hi">${high}</span></span></div>`;
    }
    return `<div class="fb-day-wx"><ha-icon icon="${icon}" style="color:${color}"></ha-icon><span class="fb-wx-hi">${high}</span></div>`;
  }

  async _fetchEvents(entities, start, end) {
    if (!this._hass || !entities.length) {
      this._events = [];
      this._render();
      return;
    }
    this._loading = true;
    this._error = null;
    this._render();
    try {
      const startIso = encodeURIComponent(start.toISOString());
      const endIso = encodeURIComponent(end.toISOString());
      const results = await Promise.all(
        entities.map((entity_id) =>
          this._hass
            .callApi(
              "GET",
              `calendars/${entity_id}?start=${startIso}&end=${endIso}`
            )
            .then((r) => ({ entity_id, events: Array.isArray(r) ? r : [] }))
            .catch((e) => {
              console.warn("familyboard-calendar-card: fetch failed", entity_id, e);
              return { entity_id, events: [] };
            })
        )
      );
      this._events = this._mergeEvents(results);
    } catch (e) {
      this._error = String(e?.message || e);
      this._events = [];
    } finally {
      this._loading = false;
      this._render();
    }
  }

  // Merge per-entity events; dedup shared events into single block with sources[]
  _mergeEvents(results) {
    const byKey = new Map();
    for (const { entity_id, events } of results) {
      for (const ev of events) {
        const start = ev.start?.dateTime || ev.start?.date;
        const end = ev.end?.dateTime || ev.end?.date;
        if (!start || !end) continue;
        const allDay = !ev.start?.dateTime;
        const summary = (ev.summary || "").trim();
        const key = `${start}|${end}|${summary.toLowerCase()}|${allDay ? "ad" : "td"}`;
        if (byKey.has(key)) {
          const cur = byKey.get(key);
          if (!cur.sources.includes(entity_id)) cur.sources.push(entity_id);
        } else {
          byKey.set(key, {
            startStr: start,
            endStr: end,
            startDate: allDay ? this._parseLocalDate(start) : new Date(start),
            endDate: allDay ? this._parseLocalDate(end) : new Date(end),
            allDay,
            summary,
            location: ev.location || "",
            description: ev.description || "",
            uid: ev.uid || ev.recurrence_id || "",
            sources: [entity_id],
          });
        }
      }
    }
    // Sort by start
    return Array.from(byKey.values()).sort((a, b) => a.startDate - b.startDate);
  }

  // ---------- styling ----------

  _eventBackground(event) {
    // Reminder events use their member color directly
    if (event.isReminder) {
      return event.color || "#888";
    }
    // If event comes from a shared calendar, use member colors instead of source colors
    const sharedMap = this._effectiveSharedCalendars();
    let colors;
    const sharedCal = event.sources.find((s) => sharedMap[s]);
    if (sharedCal) {
      const members = sharedMap[sharedCal].members || [];
      colors = members
        .map((m) => this._memberColor(m))
        .filter(Boolean);
      if (!colors.length) {
        colors = [sharedMap[sharedCal].color || this._entityColor(sharedCal)];
      }
    } else {
      colors = event.sources.map((s) => this._entityColor(s, this._config.entities.indexOf(s)));
    }
    if (colors.length === 1) return colors[0];
    const step = 100 / colors.length;
    const stops = colors
      .map((c, i) => `${c} ${i * step}% ${(i + 1) * step}%`)
      .join(", ");
    return `linear-gradient(135deg, ${stops})`;
  }

  _formatTime(d) {
    return d.toLocaleTimeString(this._config.locale, { hour: "2-digit", minute: "2-digit" });
  }

  _formatDate(d, opts) {
    return d.toLocaleDateString(this._config.locale, opts || { weekday: "long", day: "numeric", month: "long" });
  }

  // ---------- navigation ----------

  _navPrev() {
    const view = this._activeView();
    if (view === "month") {
      const d = new Date(this._currentStart);
      d.setMonth(d.getMonth() - 1);
      this._currentStart = this._startOfDay(d);
    } else {
      const step =
        view === "day" ? 1
        : view === "2days" ? 2
        : view === "workweek" ? 7
        : view === "week" ? 7
        : view === "2weeks" ? 14
        : 1;
      this._currentStart = this._addDays(this._currentStart, -step);
    }
    this._fetchKey = null;
    this._maybeFetch();
    this._render();
  }

  _navNext() {
    const view = this._activeView();
    if (view === "month") {
      const d = new Date(this._currentStart);
      d.setMonth(d.getMonth() + 1);
      this._currentStart = this._startOfDay(d);
    } else {
      const step =
        view === "day" ? 1
        : view === "2days" ? 2
        : view === "workweek" ? 7
        : view === "week" ? 7
        : view === "2weeks" ? 14
        : 1;
      this._currentStart = this._addDays(this._currentStart, step);
    }
    this._fetchKey = null;
    this._maybeFetch();
    this._render();
  }

  _navToday() {
    this._currentStart = this._startOfDay(new Date());
    this._fetchKey = null;
    this._maybeFetch();
    this._render();
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      })
    );
  }

  _showEventDialog(event) {
    // For now: open more-info on the first source calendar.
    // A future enhancement could be a custom event-detail popup.
    this._openMoreInfo(event.sources[0]);
  }

  // ---------- rendering ----------

  _render() {
    if (!this._hass) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    if (!this.shadowRoot.querySelector("ha-card")) {
      this.shadowRoot.innerHTML = this._baseTemplate();
      this._wireBaseEvents();
    }
    const view = this._activeView();
    const body = this.shadowRoot.querySelector(".fb-body");
    const title = this.shadowRoot.querySelector(".fb-title");
    title.textContent = this._headerTitle(view);

    if (!this._config.entities || !this._config.entities.length) {
      body.innerHTML = `<div class="fb-empty">Geen kalender-entiteiten geconfigureerd.</div>`;
      return;
    }

    if (view === "day") {
      body.innerHTML = this._renderTimeGrid(1);
    } else if (view === "2days") {
      body.innerHTML = this._renderTimeGrid(2);
    } else if (view === "workweek") {
      body.innerHTML = this._renderTimeGrid(5);
    } else if (view === "week") {
      body.innerHTML = this._renderTimeGrid(7);
    } else if (view === "2weeks") {
      body.innerHTML = this._renderTimeGrid(14);
    } else if (view === "month") {
      body.innerHTML = this._renderMonthGrid();
    }
    this._wireEventClicks();
    this._scrollToHour();
  }

  _baseTemplate() {
    const css = `
      :host { display: block; }
      ha-card {
        padding: 0;
        overflow: hidden;
        --fb-border: var(--divider-color, rgba(255,255,255,0.12));
        --fb-muted: var(--secondary-text-color);
        --fb-bg-alt: var(--secondary-background-color, rgba(255,255,255,0.04));
      }
      .fb-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 10px 14px;
        border-bottom: 1px solid var(--fb-border);
      }
      .fb-title { font-weight: 500; font-size: 1.05em; flex: 1; }
      .fb-nav { display: flex; gap: 4px; align-items: center; }
      .fb-btn {
        background: transparent;
        color: inherit;
        border: 1px solid var(--fb-border);
        border-radius: 14px;
        padding: 4px 10px;
        font: inherit;
        cursor: pointer;
        line-height: 1;
      }
      .fb-btn:hover { background: var(--fb-bg-alt); }
      .fb-icon-btn {
        background: transparent;
        color: inherit;
        border: none;
        border-radius: 50%;
        width: 30px; height: 30px;
        cursor: pointer;
        font-size: 1.2em;
        line-height: 1;
      }
      .fb-icon-btn:hover { background: var(--fb-bg-alt); }
      .fb-body { position: relative; }
      .fb-loading {
        position: absolute; top: 6px; right: 10px;
        font-size: 0.75em; color: var(--fb-muted);
      }
      .fb-error { padding: 12px; color: var(--error-color, #e74c3c); font-size: 0.9em; }

      .fb-grid {
        display: grid;
        grid-template-columns: 56px 1fr;
        position: relative;
      }
      .fb-grid.cols-2 { grid-template-columns: 56px repeat(2, 1fr); }
      .fb-grid.cols-5 { grid-template-columns: 56px repeat(5, 1fr); }
      .fb-grid.cols-7 { grid-template-columns: 56px repeat(7, 1fr); }
      .fb-grid.cols-14 { grid-template-columns: 56px repeat(14, minmax(60px, 1fr)); overflow-x: auto; }

      .fb-day-headers {
        display: contents;
      }
      .fb-day-header {
        padding: 6px 8px;
        text-align: center;
        border-bottom: 1px solid var(--fb-border);
        font-size: 0.85em;
        position: sticky; top: 0;
        background: var(--card-background-color, var(--ha-card-background, #1c1c1c));
        z-index: 3;
      }
      .fb-day-header.today { color: var(--primary-color); font-weight: 600; }
      .fb-day-header .fb-dow { font-size: 0.75em; opacity: 0.7; }
      .fb-day-header .fb-dnum { font-size: 1.1em; }
      .fb-day-header .fb-day-date { line-height: 1.15; }
      .fb-day-wx {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.85em;
        opacity: 0.95;
      }
      .fb-day-wx ha-icon { --mdc-icon-size: 20px; }
      .fb-day-wx .fb-wx-lo { opacity: 0.65; }

      .fb-allday-row {
        display: contents;
      }
      .fb-allday-cell {
        border-bottom: 1px solid var(--fb-border);
        border-left: 1px solid var(--fb-border);
        padding: 2px;
        min-height: 22px;
        position: relative;
      }
      .fb-allday-label {
        border-bottom: 1px solid var(--fb-border);
        padding: 4px;
        font-size: 0.7em;
        color: var(--fb-muted);
        text-align: right;
      }
      .fb-allday-event {
        display: block;
        padding: 2px 6px;
        margin: 1px 0;
        font-size: 0.78em;
        border-radius: 3px;
        color: white;
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-shadow: 0 1px 1px rgba(0,0,0,0.4);
      }
      .fb-event.fb-reminder, .fb-allday-event.fb-reminder {
        box-shadow: inset 0 0 0 999px rgba(0,0,0,0.28), 0 1px 2px rgba(0,0,0,0.3);
      }

      .fb-hours-axis {
        border-right: 1px solid var(--fb-border);
        position: relative;
      }
      .fb-hour-label {
        height: var(--fb-hour-height);
        font-size: 0.72em;
        color: var(--fb-muted);
        text-align: right;
        padding-right: 4px;
        position: relative;
        top: -7px;
      }
      .fb-hour-label:first-child { top: 0; }

      .fb-day-col {
        border-left: 1px solid var(--fb-border);
        position: relative;
        background:
          repeating-linear-gradient(
            to bottom,
            transparent 0,
            transparent calc(var(--fb-hour-height) - 1px),
            var(--fb-border) calc(var(--fb-hour-height) - 1px),
            var(--fb-border) var(--fb-hour-height)
          );
      }
      .fb-day-col.today {
        background-color: rgba(255, 200, 0, 0.04);
      }
      .fb-event {
        position: absolute;
        left: 2px;
        right: 2px;
        border-radius: 4px;
        border: 1px solid rgba(0,0,0,0.45);
        color: white;
        padding: 2px 5px;
        font-size: 0.78em;
        line-height: 1.2;
        cursor: pointer;
        overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,0.3);
        text-shadow: 0 1px 1px rgba(0,0,0,0.4);
        box-sizing: border-box;
      }
      .fb-event .fb-ev-time { font-size: 0.85em; opacity: 0.95; }
      .fb-event .fb-ev-title {
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
      }
      .fb-event.fb-compact {
        padding: 2px 6px;
        line-height: 1.1;
        display: flex;
        align-items: center;
      }
      .fb-event.fb-compact .fb-ev-line {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 0.78em;
        width: 100%;
      }
      .fb-event.fb-compact .fb-ev-time {
        font-weight: 600;
        margin-right: 4px;
      }
      .fb-event.fb-compact .fb-ev-title {
        font-weight: 400;
        display: inline;
      }
      .fb-event.fb-clipped-top::before,
      .fb-event.fb-clipped-bot::after {
        content: "▲";
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        font-size: 0.7em;
        opacity: 0.8;
      }
      .fb-event.fb-clipped-top::before { top: 0; }
      .fb-event.fb-clipped-bot::after { content: "▼"; bottom: 0; }

      .fb-now-line {
        position: absolute;
        left: 0; right: 0;
        height: 0;
        border-top: 2px solid var(--error-color, #e74c3c);
        z-index: 5;
        pointer-events: none;
      }
      .fb-now-line::before {
        content: "";
        position: absolute;
        left: -4px; top: -4px;
        width: 8px; height: 8px;
        background: var(--error-color, #e74c3c);
        border-radius: 50%;
      }

      .fb-month-placeholder {
        padding: 30px;
        text-align: center;
        color: var(--fb-muted);
      }

      .fb-month-dow {
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        position: sticky; top: 0; z-index: 3;
        background: var(--card-background-color, var(--ha-card-background, #1c1c1c));
        border-bottom: 1px solid var(--fb-border);
      }
      .fb-mc-dow {
        text-align: center;
        font-size: 0.78em;
        color: var(--fb-muted);
        padding: 6px 4px;
      }
      .fb-month-grid {
        display: flex;
        flex-direction: column;
      }
      .fb-month-week {
        display: grid;
        grid-template-columns: repeat(7, minmax(0, 1fr));
        grid-template-rows: 24px repeat(3, 18px) 14px;
        position: relative;
        border-bottom: 1px solid var(--fb-border);
      }
      .fb-month-week:last-child { border-bottom: none; }
      .fb-mc-bg {
        grid-row: 1 / -1;
        border-right: 1px solid var(--fb-border);
        z-index: 0;
      }
      .fb-mc-bg:nth-child(7n) { border-right: none; }
      .fb-mc-bg.fb-mc-other { background: var(--fb-bg-alt); }
      .fb-mc-bg.fb-mc-weekend:not(.fb-mc-other) { background: rgba(255,255,255,0.02); }
      .fb-mc-bg.fb-mc-today {
        background: color-mix(in srgb, var(--primary-color) 10%, transparent);
      }
      .fb-mc-head {
        grid-row: 1;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 2px 4px;
        font-size: 0.82em;
        line-height: 1.2;
        z-index: 1;
        pointer-events: none;
      }
      .fb-mc-head.fb-mc-today .fb-mc-num {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        border-radius: 999px;
        padding: 0 6px;
        font-weight: 600;
      }
      .fb-mc-num {
        display: inline-block;
        min-width: 18px;
        text-align: center;
      }
      .fb-mc-head .fb-day-wx {
        font-size: 0.85em;
        opacity: 0.85;
      }
      .fb-mc-bar {
        margin: 0 2px;
        padding: 0 5px;
        font-size: 0.7em;
        line-height: 16px;
        height: 16px;
        border-radius: 3px;
        color: #fff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
        z-index: 1;
      }
      .fb-mc-bar.fb-mc-cont-prev { border-top-left-radius: 0; border-bottom-left-radius: 0; margin-left: 0; }
      .fb-mc-bar.fb-mc-cont-next { border-top-right-radius: 0; border-bottom-right-radius: 0; margin-right: 0; }
      .fb-mc-more {
        grid-row: 5;
        font-size: 0.65em;
        color: var(--fb-muted);
        padding: 0 4px;
        text-align: left;
        z-index: 1;
        pointer-events: none;
      }

      .fb-empty {
        padding: 30px;
        text-align: center;
        color: var(--fb-muted);
        font-size: 0.9em;
      }
    `;
    return `
      <ha-card>
        <style>${css}</style>
        <div class="fb-header">
          <button class="fb-icon-btn" data-act="prev" title="Vorige">‹</button>
          <button class="fb-btn" data-act="today">Vandaag</button>
          <button class="fb-icon-btn" data-act="next" title="Volgende">›</button>
          <div class="fb-title"></div>
        </div>
        <div class="fb-body"><div class="fb-empty">Laden…</div></div>
      </ha-card>
    `;
  }

  _wireBaseEvents() {
    const root = this.shadowRoot;
    root.querySelector('[data-act="prev"]')?.addEventListener("click", () => this._navPrev());
    root.querySelector('[data-act="next"]')?.addEventListener("click", () => this._navNext());
    root.querySelector('[data-act="today"]')?.addEventListener("click", () => this._navToday());
  }

  _headerTitle(view) {
    const start = this._currentStart;
    if (view === "day") {
      return this._formatDate(start, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }
    if (view === "2days" || view === "workweek" || view === "week" || view === "2weeks") {
      const len =
        view === "2days" ? 1
        : view === "workweek" ? 4
        : view === "week" ? 6
        : 13;
      const end = this._addDays(start, len);
      const sm = start.toLocaleDateString(this._config.locale, { day: "numeric", month: "short" });
      const em = end.toLocaleDateString(this._config.locale, { day: "numeric", month: "short", year: "numeric" });
      return `${sm} – ${em}`;
    }
    if (view === "month") {
      return start.toLocaleDateString(this._config.locale, { month: "long", year: "numeric" });
    }
    return "";
  }

  _renderTimeGrid(numDays) {
    const cfg = this._config;
    const hourHeight = (60 / cfg.slot_minutes) * cfg.row_height; // px per hour

    const days = [];
    for (let i = 0; i < numDays; i++) days.push(this._addDays(this._currentStart, i));
    const today = this._startOfDay(new Date());

    // Combine calendar events with reminder pseudo-events
    const reminderEvents = this._buildReminderEvents();
    const allEvents = [...this._events, ...reminderEvents];

    // partition events per day
    const eventsByDay = days.map(() => ({ allDay: [], timed: [] }));
    for (const ev of allEvents) {
      for (let i = 0; i < days.length; i++) {
        if (this._eventOnDay(ev, days[i])) {
          if (ev.allDay || this._spansFullDay(ev, days[i])) eventsByDay[i].allDay.push(ev);
          else eventsByDay[i].timed.push(ev);
        }
      }
    }

    // Extend hour range for events that start/end on this day.
    // Spillover entirely outside config range still gets visible by extending bounds.
    let startHour = cfg.start_hour;
    let endHour = cfg.end_hour;
    const occupiedHours = new Set();
    for (let i = 0; i < days.length; i++) {
      const dStart = this._startOfDay(days[i]);
      const dEnd = this._addDays(dStart, 1);
      for (const ev of eventsByDay[i].timed) {
        const startsToday = ev.startDate >= dStart && ev.startDate < dEnd;
        const endsToday = ev.endDate > dStart && ev.endDate <= dEnd;
        if (startsToday) {
          const sH = (ev.startDate - dStart) / 3600000;
          if (sH < startHour) startHour = Math.max(0, Math.floor(sH));
        }
        if (endsToday) {
          const eH = (ev.endDate - dStart) / 3600000;
          // If event ends before current startHour (spillover from previous day), extend down
          if (eH < startHour) startHour = Math.max(0, Math.floor(eH));
          if (eH > endHour) endHour = Math.min(24, Math.ceil(eH));
        }
        const evStartLocal = ev.startDate < dStart ? dStart : ev.startDate;
        const evEndLocal = ev.endDate > dEnd ? dEnd : ev.endDate;
        const sHc = (evStartLocal - dStart) / 3600000;
        const eHc = (evEndLocal - dStart) / 3600000;
        for (let h = Math.floor(sHc); h < Math.ceil(eHc); h++) {
          if (h >= 0 && h < 24) occupiedHours.add(h);
        }
      }
    }
    const totalHours = endHour - startHour;
    const gridHeight = totalHours * hourHeight;

    const colsClass =
      numDays === 2 ? " cols-2"
      : numDays === 5 ? " cols-5"
      : numDays === 7 ? " cols-7"
      : numDays === 14 ? " cols-14"
      : "";

    // Header row + all-day row
    let dayHeaders = `<div class="fb-day-header" style="border-right:1px solid var(--fb-border);"></div>`;
    let alldayCells = `<div class="fb-allday-label">Hele dag</div>`;
    for (let i = 0; i < numDays; i++) {
      const d = days[i];
      const isToday = this._isSameDay(d, today);
      const wx = this._renderWeather(d);
      dayHeaders += `<div class="fb-day-header${isToday ? " today" : ""}${wx ? " has-wx" : ""}">
        <div class="fb-day-date">
          <div class="fb-dow">${d.toLocaleDateString(cfg.locale, { weekday: "short" })}</div>
          <div class="fb-dnum">${d.getDate()}</div>
        </div>
        ${wx}
      </div>`;
      const adHtml = eventsByDay[i].allDay
        .map((ev, idx) => this._renderAllDayBlock(ev, idx))
        .join("");
      alldayCells += `<div class="fb-allday-cell">${adHtml}</div>`;
    }

    // Day columns + now-line
    let dayCols = "";
    const nowMinutes = this._minutesSinceMidnight(new Date());
    for (let i = 0; i < numDays; i++) {
      const d = days[i];
      const isToday = this._isSameDay(d, today);
      const timed = this._layoutOverlap(eventsByDay[i].timed);
      const blocks = timed
        .map((slot) => this._renderTimedBlock(slot, d, hourHeight, startHour, endHour))
        .join("");
      const nowLine =
        cfg.show_now_indicator && isToday && nowMinutes >= startHour * 60 && nowMinutes <= endHour * 60
          ? `<div class="fb-now-line" style="top:${((nowMinutes - startHour * 60) / 60) * hourHeight}px;"></div>`
          : "";
      dayCols += `<div class="fb-day-col${isToday ? " today" : ""}" style="height:${gridHeight}px;">${blocks}${nowLine}</div>`;
    }

    // Hours-axis: absolute-positioned labels aligned with grid lines
    const axisCol = `<div class="fb-hours-axis" style="height:${gridHeight}px;position:relative;">${this._buildHourLabels(startHour, endHour, hourHeight, occupiedHours)}</div>`;

    const loading = this._loading ? `<div class="fb-loading">…</div>` : "";
    const error = this._error ? `<div class="fb-error">⚠ ${this._error}</div>` : "";

    return `
      ${error}
      ${loading}
      <div class="fb-grid${colsClass}" style="--fb-hour-height:${hourHeight}px;">
        ${dayHeaders}
        ${alldayCells}
        ${axisCol}
        ${dayCols}
      </div>
    `;
  }

  _buildHourLabels(startHour, endHour, hourHeight, occupiedHours) {
    let html = "";
    for (let h = startHour; h <= endHour; h++) {
      // Smart-skip startHour label if no event overlaps it (avoids visual clash with all-day row)
      if (h === startHour && occupiedHours && !occupiedHours.has(h)) continue;
      // Smart-skip endHour label too if no event overlaps the previous hour
      if (h === endHour && occupiedHours && !occupiedHours.has(h - 1)) continue;
      const top = (h - startHour) * hourHeight;
      let translate = "translateY(2px)";
      if (h === endHour) translate = "translateY(-100%)";
      const label = h === 24 ? "24:00" : `${String(h).padStart(2, "0")}:00`;
      html += `<div class="fb-hour-label" style="position:absolute;top:${top}px;right:4px;transform:${translate};">${label}</div>`;
    }
    return html;
  }

  // Build pseudo-events from sensor.familyboard_tasks attribute items
  _buildReminderEvents() {
    if (!this._hass || !this._config.reminders_entity) return [];
    // If hide-switch is ON → reminders are shown elsewhere → don't duplicate them in calendar
    if (this._config.reminders_hide_when) {
      const sw = this._hass.states[this._config.reminders_hide_when];
      if (sw && sw.state === "on") return [];
    }
    const sensor = this._hass.states[this._config.reminders_entity];
    const items = sensor?.attributes?.items;
    if (!Array.isArray(items)) return [];
    const out = [];
    for (const item of items) {
      const summary = (item.summary || "").trim();
      if (!summary) continue;
      let startDate = null;
      let endDate = null;
      let allDay = false;
      if (item.start) {
        startDate = new Date(item.start);
        endDate = item.end ? new Date(item.end) : new Date(startDate.getTime() + 30 * 60000);
      } else if (item.due) {
        startDate = this._parseLocalDate(item.due);
        endDate = this._addDays(startDate, 1);
        allDay = true;
      } else {
        continue; // no date → skip
      }
      if (Number.isNaN(startDate.getTime())) continue;
      out.push({
        startDate,
        endDate,
        allDay,
        summary,
        location: "",
        description: item.description || "",
        sources: [],
        isReminder: true,
        color: item.color || "#888",
        todoEntity: item.todo_entity || null,
        uid: item.uid || "",
      });
    }
    return out;
  }

  _renderMonthGrid() {
    const cfg = this._config;
    const today = this._startOfDay(new Date());
    const monthIdx = this._currentStart.getMonth();
    const [gridStart] = this._visibleRange();

    const days = [];
    for (let i = 0; i < 42; i++) days.push(this._addDays(gridStart, i));

    // Combine calendar events with reminder pseudo-events
    const reminderEvents = this._buildReminderEvents();
    const allEvents = [...this._events, ...reminderEvents];

    // Weekday header row, starting at firstWeekday
    let dowHeader = "";
    for (let i = 0; i < 7; i++) {
      const sample = this._addDays(gridStart, i);
      const label = sample.toLocaleDateString(cfg.locale, { weekday: "short" });
      dowHeader += `<div class="fb-mc-dow">${this._escape(label)}</div>`;
    }

    const MAX_SLOTS = 3; // visible event rows per week
    let weeksHtml = "";
    for (let w = 0; w < 6; w++) {
      const weekStart = days[w * 7];
      const weekEnd = this._addDays(weekStart, 7); // exclusive

      // Build segments: one per (event × week) overlap, with span 1..7
      const segments = [];
      for (const ev of allEvents) {
        if (!(ev.endDate > weekStart && ev.startDate < weekEnd)) continue;
        const segStart = ev.startDate < weekStart ? weekStart : this._startOfDay(ev.startDate);
        // For all-day events endDate is exclusive midnight.
        // For timed events ending mid-day, the segment ends on that day.
        const lastDayCandidate = new Date(ev.endDate.getTime() - 1);
        const segLast = lastDayCandidate >= weekEnd
          ? this._addDays(weekEnd, -1)
          : this._startOfDay(lastDayCandidate);
        const startDow = Math.round((segStart - weekStart) / 86400000);
        const span = Math.round((segLast - segStart) / 86400000) + 1;
        if (span < 1) continue;
        const isContinuationFromPrev = ev.startDate < weekStart;
        const isContinuationToNext = ev.endDate > weekEnd;
        segments.push({
          ev,
          startDow: Math.max(0, startDow),
          span: Math.min(7 - Math.max(0, startDow), span),
          isContPrev: isContinuationFromPrev,
          isContNext: isContinuationToNext,
        });
      }

      // Sort: longer spans first, then earlier start, all-day before timed
      segments.sort((a, b) => {
        const ad = a.ev.allDay || this._spansFullDay(a.ev, weekStart) ? 0 : 1;
        const bd = b.ev.allDay || this._spansFullDay(b.ev, weekStart) ? 0 : 1;
        if (ad !== bd) return ad - bd;
        if (b.span !== a.span) return b.span - a.span;
        return a.ev.startDate - b.ev.startDate;
      });

      // Greedy slot assignment: lowest free slot for the segment's columns
      const used = new Set(); // "dow|slot"
      const placed = [];
      for (const seg of segments) {
        let s = 0;
        // safety cap to avoid runaway
        while (s < 32) {
          let ok = true;
          for (let d = seg.startDow; d < seg.startDow + seg.span; d++) {
            if (used.has(`${d}|${s}`)) { ok = false; break; }
          }
          if (ok) break;
          s++;
        }
        for (let d = seg.startDow; d < seg.startDow + seg.span; d++) {
          used.add(`${d}|${s}`);
        }
        placed.push({ ...seg, slot: s });
      }

      // Background day cells (row 1 / -1, full week-row height)
      let bgs = "";
      let heads = "";
      for (let dow = 0; dow < 7; dow++) {
        const d = days[w * 7 + dow];
        const isToday = this._isSameDay(d, today);
        const isOther = d.getMonth() !== monthIdx;
        const isWeekend = d.getDay() === 0 || d.getDay() === 6;
        const bgClasses = [
          "fb-mc-bg",
          isToday ? "fb-mc-today" : "",
          isOther ? "fb-mc-other" : "",
          isWeekend ? "fb-mc-weekend" : "",
        ].filter(Boolean).join(" ");
        bgs += `<div class="${bgClasses}" style="grid-column:${dow + 1};"></div>`;
        const wx = this._renderWeather(d);
        const headClasses = ["fb-mc-head", isToday ? "fb-mc-today" : ""].filter(Boolean).join(" ");
        heads += `<div class="${headClasses}" style="grid-column:${dow + 1};">
          <span class="fb-mc-num">${d.getDate()}</span>
          ${wx}
        </div>`;
      }

      // Render bars (slot < MAX_SLOTS) and count overflow per dow
      const overflowByDow = new Array(7).fill(0);
      let bars = "";
      for (const p of placed) {
        if (p.slot >= MAX_SLOTS) {
          for (let d = p.startDow; d < p.startDow + p.span; d++) overflowByDow[d]++;
          continue;
        }
        bars += this._renderMonthBar(p, weekStart);
      }
      let mores = "";
      for (let dow = 0; dow < 7; dow++) {
        if (overflowByDow[dow] > 0) {
          mores += `<span class="fb-mc-more" style="grid-column:${dow + 1};">+${overflowByDow[dow]} meer</span>`;
        }
      }

      weeksHtml += `<div class="fb-month-week">${bgs}${heads}${bars}${mores}</div>`;
    }

    const error = this._error ? `<div class="fb-error">⚠ ${this._error}</div>` : "";
    const loading = this._loading ? `<div class="fb-loading">…</div>` : "";

    return `
      ${error}
      ${loading}
      <div class="fb-month-dow">${dowHeader}</div>
      <div class="fb-month-grid">${weeksHtml}</div>
    `;
  }

  _renderMonthBar(seg, weekStart) {
    const ev = seg.ev;
    const bg = this._eventBackground(ev);
    const reminderCls = ev.isReminder ? " fb-reminder" : "";
    const dataAttr = ev.isReminder
      ? `data-todo="${this._escape(ev.todoEntity || "")}" data-uid="${this._escape(ev.uid || "")}"`
      : `data-sources="${encodeURIComponent(JSON.stringify(ev.sources))}"`;
    const segDay = this._addDays(weekStart, seg.startDow);
    const isAllDay = ev.allDay || this._spansFullDay(ev, segDay);
    const prefix = ev.isReminder
      ? "🔔 "
      : isAllDay || seg.span > 1 || seg.isContPrev
        ? ""
        : `${this._formatTime(ev.startDate)} `;
    const contClasses = [
      seg.isContPrev ? "fb-mc-cont-prev" : "",
      seg.isContNext ? "fb-mc-cont-next" : "",
    ].filter(Boolean).join(" ");
    const arrowL = seg.isContPrev ? "‹ " : "";
    const arrowR = seg.isContNext ? " ›" : "";
    return `<span class="fb-mc-bar${reminderCls} ${contClasses}" ${dataAttr}
      style="grid-column:${seg.startDow + 1} / span ${seg.span}; grid-row:${seg.slot + 2}; background:${bg};"
      title="${this._escape(ev.summary || "")}">${arrowL}${prefix}${this._escape(ev.summary || "(geen titel)")}${arrowR}</span>`;
  }

  // Does the event overlap day d (00:00 - 24:00)?
  _eventOnDay(ev, d) {
    const dStart = this._startOfDay(d);
    const dEnd = this._addDays(dStart, 1);
    return ev.endDate > dStart && ev.startDate < dEnd;
  }

  // True if a timed event covers the whole day (treat as all-day for layout)
  _spansFullDay(ev, d) {
    if (ev.allDay) return true;
    const dStart = this._startOfDay(d);
    const dEnd = this._addDays(dStart, 1);
    return ev.startDate <= dStart && ev.endDate >= dEnd;
  }

  _minutesSinceMidnight(d) {
    return d.getHours() * 60 + d.getMinutes();
  }

  // Sweep-line overlap layout: returns [{event, col, cols}]
  _layoutOverlap(events) {
    const sorted = events.slice().sort((a, b) => a.startDate - b.startDate || b.endDate - a.endDate);
    const result = [];
    const groups = []; // active groups
    let currentGroup = [];
    let groupEnd = null;
    for (const ev of sorted) {
      if (currentGroup.length && groupEnd && ev.startDate >= groupEnd) {
        // flush
        this._assignColumns(currentGroup, result);
        currentGroup = [];
        groupEnd = null;
      }
      currentGroup.push(ev);
      if (!groupEnd || ev.endDate > groupEnd) groupEnd = ev.endDate;
    }
    if (currentGroup.length) this._assignColumns(currentGroup, result);
    return result;
  }

  _assignColumns(group, result) {
    const cols = []; // each col is array of events; first non-conflicting wins
    for (const ev of group) {
      let placed = false;
      for (let i = 0; i < cols.length; i++) {
        const last = cols[i][cols[i].length - 1];
        if (last.endDate <= ev.startDate) {
          cols[i].push(ev);
          ev.__col = i;
          placed = true;
          break;
        }
      }
      if (!placed) {
        cols.push([ev]);
        ev.__col = cols.length - 1;
      }
    }
    const total = cols.length;
    for (const ev of group) {
      result.push({ event: ev, col: ev.__col, cols: total });
      delete ev.__col;
    }
  }

  _renderTimedBlock(slot, day, hourHeight, startHour, endHour) {
    const ev = slot.event;
    const dayStart = this._startOfDay(day);
    const dayEnd = this._addDays(dayStart, 1);
    const evStart = ev.startDate < dayStart ? dayStart : ev.startDate;
    const evEnd = ev.endDate > dayEnd ? dayEnd : ev.endDate;
    const startMin = (evStart - dayStart) / 60000;
    const endMin = (evEnd - dayStart) / 60000;

    const visibleStart = Math.max(startMin, startHour * 60);
    const visibleEnd = Math.min(endMin, endHour * 60);
    if (visibleEnd <= visibleStart) return ""; // entirely outside range

    const top = ((visibleStart - startHour * 60) / 60) * hourHeight;
    const durationMin = visibleEnd - visibleStart;
    const height = Math.max((durationMin / 60) * hourHeight, 22);
    const widthPct = 100 / slot.cols;
    const leftPct = slot.col * widthPct;

    const clippedTop = startMin < startHour * 60;
    const clippedBot = endMin > endHour * 60;
    const reminderCls = ev.isReminder ? " fb-reminder" : "";
    const compact = !ev.allDay && durationMin <= 30;
    const compactCls = compact ? " fb-compact" : "";
    const cls = `fb-event${clippedTop ? " fb-clipped-top" : ""}${clippedBot ? " fb-clipped-bot" : ""}${reminderCls}${compactCls}`;

    const bg = this._eventBackground(ev);
    const time = ev.allDay ? "" : `${this._formatTime(ev.startDate)}`;
    const titlePrefix = ev.isReminder ? "🔔 " : "";
    const title = titlePrefix + this._escape(ev.summary || "(geen titel)");
    const dataAttr = ev.isReminder
      ? `data-todo="${this._escape(ev.todoEntity || "")}" data-uid="${this._escape(ev.uid || "")}"`
      : `data-sources="${encodeURIComponent(JSON.stringify(ev.sources))}"`;

    const inner = compact
      ? `<div class=\"fb-ev-line\"><span class=\"fb-ev-time\">${time}</span> <span class=\"fb-ev-title\">${title}</span></div>`
      : `<div class=\"fb-ev-time\">${time}</div><div class=\"fb-ev-title\">${title}</div>`;

    return `
      <div class="${cls}"
           ${dataAttr}
           style="top:${top}px;height:${height}px;left:calc(${leftPct}% + 1px);width:calc(${widthPct}% - 4px);background:${bg};">
        ${inner}
      </div>
    `;
  }

  _renderAllDayBlock(ev, idx) {
    const bg = this._eventBackground(ev);
    const reminderCls = ev.isReminder ? " fb-reminder" : "";
    const prefix = ev.isReminder ? "🔔 " : "";
    const dataAttr = ev.isReminder
      ? `data-todo="${this._escape(ev.todoEntity || "")}" data-uid="${this._escape(ev.uid || "")}"`
      : `data-sources="${encodeURIComponent(JSON.stringify(ev.sources))}"`;
    return `<span class="fb-allday-event${reminderCls}" ${dataAttr} style="background:${bg};">${prefix}${this._escape(ev.summary || "(geen titel)")}</span>`;
  }

  _wireEventClicks() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-sources]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        try {
          const sources = JSON.parse(decodeURIComponent(el.dataset.sources));
          if (sources && sources[0]) this._openMoreInfo(sources[0]);
        } catch (_) { /* noop */ }
      });
    });
    root.querySelectorAll("[data-todo]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const todo = el.dataset.todo;
        if (todo) this._openMoreInfo(todo);
      });
    });
  }

  _scrollToHour() {
    // Scroll to ~current hour on first render of day view today (best-effort)
    // Skipped to avoid reflow loops; could add scrollIntoView later.
  }

  _escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  static getStubConfig() {
    return {
      entities: [],
      view: "day",
      filter_entity: "select.familyboard_calendar",
      view_entity: "select.familyboard_view",
    };
  }

  static async getConfigElement() {
    await customElements.whenDefined("ha-form");
    return document.createElement("familyboard-calendar-card-editor");
  }
}

const CALENDAR_EDITOR_SCHEMA = [
  {
    name: "entities",
    selector: { entity: { domain: "calendar", multiple: true } },
  },
  {
    name: "view",
    selector: {
      select: {
        options: [
          { value: "day", label: "Day" },
          { value: "week", label: "Week" },
          { value: "2weeks", label: "2 Weeks" },
          { value: "month", label: "Month" },
        ],
      },
    },
  },
  { name: "filter_entity", selector: { entity: { domain: "select" } } },
  { name: "view_entity", selector: { entity: { domain: "select" } } },
  { name: "weather_entity", selector: { entity: { domain: "weather" } } },
  { name: "weather_show_low", selector: { boolean: {} } },
  { name: "reminders_entity", selector: { entity: {} } },
  { name: "config_entity", selector: { entity: { domain: "sensor" } } },
  { name: "show_now_indicator", selector: { boolean: {} } },
  { name: "show_navigation", selector: { boolean: {} } },
  { name: "start_hour", selector: { number: { min: 0, max: 23, mode: "box" } } },
  { name: "end_hour", selector: { number: { min: 1, max: 24, mode: "box" } } },
  {
    name: "slot_minutes",
    selector: {
      select: {
        options: [
          { value: 15, label: "15" },
          { value: 20, label: "20" },
          { value: 30, label: "30" },
          { value: 60, label: "60" },
        ],
      },
    },
  },
  { name: "row_height", selector: { number: { min: 12, max: 80, mode: "box" } } },
  { name: "locale", selector: { text: {} } },
];

class FamilyBoardCalendarCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._form = null;
    this._config = {};
    this._hass = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => s.label || s.name;
      this._form.schema = CALENDAR_EDITOR_SCHEMA;
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: ev.detail.value },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this.shadowRoot.appendChild(this._form);
    }
    if (this._hass) this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

customElements.define("familyboard-calendar-card-editor", FamilyBoardCalendarCardEditor);
customElements.define("familyboard-calendar-card", FamilyBoardCalendarCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-calendar-card")) {
  window.customCards.push({
    type: "familyboard-calendar-card",
    name: "FamilyBoard Calendar Card",
    description: "Native time-grid calendar with day/week/month views, multi-color shared events.",
    documentationURL: "https://github.com/apiest/FamilyBoard#lovelace-cards",
    preview: false,
  });
}

const FB_VERSION = (() => {
  try {
    return new URL(import.meta.url).searchParams.get("v") || "dev";
  } catch (_e) {
    return "dev";
  }
})();

console.info(
  `%c FAMILYBOARD-CALENDAR-CARD %c v${FB_VERSION} `,
  "color:white;background:#4A90D9;font-weight:bold;",
  "color:#4A90D9;background:transparent;"
);
