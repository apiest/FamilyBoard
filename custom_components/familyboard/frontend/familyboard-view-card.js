/**
 * FamilyBoard View Card
 *
 * Renders chips for `select.familyboard_view` (or any select entity), reading
 * the option list from `stateObj.attributes.options` and the user-visible
 * label via `hass.formatEntityState(stateObj, option)` so labels follow the
 * Home Assistant locale (state translations live in `translations/<lang>.json`).
 *
 * Wraps `mushroom-chips-card` for visual consistency with `familyboard-filter-card`.
 *
 * Config:
 *   type: custom:familyboard-view-card
 *   entity: select.familyboard_view              # optional
 *   icons:                                       # optional, per option key
 *     today: mdi:calendar-today
 *     ...
 *   color: amber                                 # optional, selected color
 *   show_reminders: true                         # optional, append a Herinneringen toggle chip
 *   reminders_switch: switch.familyboard_show_reminders  # optional, entity backing the chip
 *   extra_chips: []                              # optional, raw mushroom-chip dicts appended
 */

const DEFAULT_ENTITY = "select.familyboard_view";
const DEFAULT_REMINDERS_SWITCH = "switch.familyboard_show_reminders";

const DEFAULT_ICONS = {
  today: "mdi:calendar-today",
  tomorrow: "mdi:calendar-arrow-right",
  week: "mdi:calendar-week",
  two_weeks: "mdi:calendar-range",
  month: "mdi:calendar-month",
  list: "mdi:view-list",
  agenda: "mdi:calendar-star",
};

class FamilyBoardViewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._inner = null;
    this._lastSig = null;
    this._mushroomReady = false;
    this._mushroomMissing = false;
    this._init();
  }

  async _init() {
    if (customElements.get("mushroom-chips-card")) {
      this._mushroomReady = true;
      return;
    }
    try {
      await Promise.race([
        customElements.whenDefined("mushroom-chips-card"),
        new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 5000)),
      ]);
      this._mushroomReady = true;
      this._lastSig = null;
      this._render();
    } catch (e) {
      this._mushroomMissing = true;
      this._lastSig = null;
      this._render();
    }
  }

  setConfig(config) {
    this._config = {
      entity: config.entity || DEFAULT_ENTITY,
      icons: { ...DEFAULT_ICONS, ...(config.icons || {}) },
      color: config.color || "amber",
      show_reminders: config.show_reminders === true,
      reminders_switch: config.reminders_switch || DEFAULT_REMINDERS_SWITCH,
      reminders_label: config.reminders_label || "Herinneringen",
      extra_chips: Array.isArray(config.extra_chips) ? config.extra_chips : [],
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 1;
  }

  getGridOptions() {
    return { rows: 1, columns: 12, max_rows: 1 };
  }

  static getStubConfig() {
    return { entity: DEFAULT_ENTITY };
  }

  _label(stateObj, option) {
    if (this._hass && typeof this._hass.formatEntityState === "function") {
      try {
        return this._hass.formatEntityState(stateObj, option);
      } catch (_e) {
        /* fall through */
      }
    }
    // Fallback: title-case the key.
    return option.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  _buildChips(stateObj) {
    const options = stateObj?.attributes?.options || [];
    const current = stateObj?.state;
    const chips = options.map((opt) => ({
      type: "template",
      icon: this._config.icons[opt] || "mdi:circle-outline",
      content: this._label(stateObj, opt),
      icon_color: opt === current ? this._config.color : "grey",
      tap_action: {
        action: "perform-action",
        perform_action: "select.select_option",
        target: { entity_id: this._config.entity },
        data: { option: opt },
      },
    }));
    if (this._config.show_reminders) {
      const swEntity = this._config.reminders_switch;
      const sw = this._hass.states[swEntity];
      const on = sw && sw.state === "on";
      chips.push({
        type: "template",
        icon: on ? "mdi:bell" : "mdi:bell-off",
        icon_color: on ? this._config.color : "grey",
        content: this._config.reminders_label,
        tap_action: {
          action: "perform-action",
          perform_action: "switch.toggle",
          target: { entity_id: swEntity },
        },
      });
    }
    for (const extra of this._config.extra_chips) {
      chips.push(extra);
    }
    return chips;
  }

  async _render() {
    if (!this._hass) return;

    if (this._mushroomMissing) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding:16px;color:var(--error-color);">
            FamilyBoard View Card vereist <b>Mushroom Cards</b>.
            Installeer via HACS en herstart.
          </div>
        </ha-card>`;
      return;
    }
    if (!this._mushroomReady) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:8px;">Loading…</div></ha-card>`;
      return;
    }

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:8px;color:var(--error-color);">${this._config.entity} not found</div></ha-card>`;
      return;
    }

    const sig = JSON.stringify({
      e: this._config.entity,
      o: stateObj.attributes.options,
      s: stateObj.state,
      lang: this._hass?.locale?.language || "",
      x: this._config.extra_chips.length,
      r: this._config.show_reminders
        ? this._hass.states[this._config.reminders_switch]?.state || ""
        : "",
    });
    if (sig === this._lastSig && this._inner) {
      this._inner.hass = this._hass;
      return;
    }
    this._lastSig = sig;

    const chips = this._buildChips(stateObj);
    const cardConfig = { type: "custom:mushroom-chips-card", chips };

    let helpers;
    try {
      helpers = await window.loadCardHelpers();
    } catch (e) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;color:var(--error-color);">loadCardHelpers unavailable</div></ha-card>`;
      return;
    }
    const el = helpers.createCardElement(cardConfig);
    el.hass = this._hass;
    this._inner = el;

    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(el);
  }

  static async getConfigElement() {
    await customElements.whenDefined("ha-form");
    return document.createElement("familyboard-view-card-editor");
  }
}

const VIEW_EDITOR_SCHEMA = [
  { name: "entity", required: true, selector: { entity: { domain: "select" } } },
  { name: "color", selector: { text: {} } },
  { name: "show_reminders", selector: { boolean: {} } },
  { name: "reminders_switch", selector: { entity: { domain: "switch" } } },
];

class FamilyBoardViewCardEditor extends HTMLElement {
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
      this._form.schema = VIEW_EDITOR_SCHEMA;
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

customElements.define("familyboard-view-card-editor", FamilyBoardViewCardEditor);
customElements.define("familyboard-view-card", FamilyBoardViewCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-view-card")) {
  window.customCards.push({
    type: "familyboard-view-card",
    name: "FamilyBoard View Card",
    description: "Localized chip selector for any FamilyBoard select entity.",
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
  `%c FAMILYBOARD-VIEW-CARD %c v${FB_VERSION} `,
  "color:white;background:#4A90D9;font-weight:bold;",
  "color:#4A90D9;background:transparent;",
);
