/**
 * FamilyBoard Filter Card
 *
 * Renders a row of member filter chips via `mushroom-chips-card`, styled
 * with `card-mod`. Reads members from `sensor.familyboard_members` and
 * writes the selection to `select.familyboard_calendar`.
 *
 * Requires HACS plugins: Mushroom Cards, card-mod.
 *
 * Config:
 *   type: custom:familyboard-filter-card
 *   filter_entity: select.familyboard_calendar    # optional
 *   members_entity: sensor.familyboard_members    # optional
 *   show_alles: true                              # optional, default true
 *   extra_chips: []                               # optional, raw mushroom-chip dicts appended
 */

const DEFAULT_FILTER = "select.familyboard_calendar";
const DEFAULT_MEMBERS = "sensor.familyboard_members";
const ALLES_LABEL = "Alles";
const ALLES_COLOR = "#8c8c8c";

class FamilyBoardFilterCard extends HTMLElement {
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
      filter_entity: config.filter_entity || DEFAULT_FILTER,
      members_entity: config.members_entity || DEFAULT_MEMBERS,
      show_alles: config.show_alles !== false,
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
    return {
      filter_entity: DEFAULT_FILTER,
      members_entity: DEFAULT_MEMBERS,
      show_alles: true,
      extra_chips: [],
    };
  }

  _hexToRgba(hex, alpha) {
    if (!hex) return `rgba(74, 144, 217, ${alpha})`;
    const m = hex.replace("#", "");
    const r = parseInt(m.substring(0, 2), 16);
    const g = parseInt(m.substring(2, 4), 16);
    const b = parseInt(m.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  _chipStyle({ color, selected }) {
    // For mushroom template chips card-mod's top-level `style` is applied
    // inside the chip element itself; `ha-card` is the pill background.
    // Setting it on `:host` doesn't paint, and `mushroom-chip$ .chip`
    // doesn't exist on template chips, which is why earlier attempts
    // never highlighted the selected chip.
    if (!selected) return "";
    const bg = this._hexToRgba(color, 0.45);
    const border = this._hexToRgba(color, 0.9);
    return `
      ha-card {
        background: ${bg} !important;
        border: 1.5px solid ${border} !important;
        transition: background-color 140ms ease, border-color 140ms ease;
      }
    `;
  }

  _buildChip({ name, color, picture, icon, selected }) {
    const filterEntity = this._config.filter_entity;
    const chip = {
      type: "template",
      content: name,
      tap_action: {
        action: "perform-action",
        perform_action: "select.select_option",
        target: { entity_id: filterEntity },
        data: { option: name },
      },
      card_mod: { style: this._chipStyle({ color, selected }) },
    };
    if (picture) {
      chip.picture = picture;
    } else {
      chip.icon = icon || "mdi:account";
      chip.icon_color = color;
    }
    return chip;
  }

  _buildChips(members, currentFilter) {
    const chips = [];
    if (this._config.show_alles) {
      chips.push(
        this._buildChip({
          name: ALLES_LABEL,
          color: ALLES_COLOR,
          icon: "mdi:account-group",
          selected: currentFilter === ALLES_LABEL,
        }),
      );
    }
    for (const m of members) {
      chips.push(
        this._buildChip({
          name: m.name,
          color: m.color,
          picture: m.picture,
          icon: "mdi:account",
          selected: currentFilter === m.name,
        }),
      );
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
            FamilyBoard Filter Card vereist <b>Mushroom Cards</b>.
            Installeer via HACS en herstart.
          </div>
        </ha-card>`;
      return;
    }
    if (!this._mushroomReady) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:8px;">Loading…</div></ha-card>`;
      return;
    }

    const membersState = this._hass.states[this._config.members_entity];
    const filterState = this._hass.states[this._config.filter_entity];
    const members = (membersState && membersState.attributes.members) || [];
    const currentFilter = filterState ? filterState.state : null;

    const sig = JSON.stringify({
      m: members.map((x) => [x.name, x.color, x.picture]),
      f: currentFilter,
      cfg: this._config.extra_chips.length,
      a: this._config.show_alles,
    });
    if (sig === this._lastSig && this._inner) {
      this._inner.hass = this._hass;
      return;
    }
    this._lastSig = sig;

    const chips = this._buildChips(members, currentFilter);
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
    return document.createElement("familyboard-filter-card-editor");
  }
}

const FILTER_EDITOR_SCHEMA = [
  { name: "filter_entity", selector: { entity: { domain: "select" } } },
  { name: "members_entity", selector: { entity: { domain: "sensor" } } },
  { name: "show_alles", selector: { boolean: {} } },
];

class FamilyBoardFilterCardEditor extends HTMLElement {
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
      this._form.schema = FILTER_EDITOR_SCHEMA;
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

customElements.define("familyboard-filter-card-editor", FamilyBoardFilterCardEditor);
customElements.define("familyboard-filter-card", FamilyBoardFilterCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-filter-card")) {
  window.customCards.push({
    type: "familyboard-filter-card",
    name: "FamilyBoard Filter Card",
    description: "Dynamic per-member filter chips for FamilyBoard",
    documentationURL: "https://github.com/apiest/FamilyBoard#lovelace-cards",
    preview: false,
  });
}
