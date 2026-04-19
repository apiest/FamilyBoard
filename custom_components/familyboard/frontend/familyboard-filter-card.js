/**
 * FamilyBoard Filter Card
 *
 * Dynamically renders a row of mushroom-chips that read members from
 * `sensor.familyboard_members` and write the selection to
 * `select.familyboard_calendar`.
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
      filter_entity: "select.familyboard_calendar",
      members_entity: "sensor.familyboard_members",
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

  _buildChips(members, currentFilter) {
    const chips = [];
    const filterEntity = this._config.filter_entity;

    if (this._config.show_alles) {
      chips.push({
        type: "template",
        icon: "mdi:account-group",
        content: ALLES_LABEL,
        tap_action: {
          action: "perform-action",
          perform_action: "select.select_option",
          target: { entity_id: filterEntity },
          data: { option: ALLES_LABEL },
        },
        card_mod: {
          style: `ha-card {
            --chip-background: ${
              currentFilter === ALLES_LABEL
                ? "rgba(140, 140, 140, 0.35)"
                : "var(--ha-card-background)"
            };
          }`,
        },
      });
    }

    for (const m of members) {
      const isSelected = currentFilter === m.name;
      const bg = isSelected
        ? this._hexToRgba(m.color, 0.35)
        : "var(--ha-card-background)";
      const chip = {
        type: "template",
        content: m.name,
        tap_action: {
          action: "perform-action",
          perform_action: "select.select_option",
          target: { entity_id: filterEntity },
          data: { option: m.name },
        },
        card_mod: {
          style: `ha-card { --chip-background: ${bg}; }`,
        },
      };
      if (m.picture) {
        chip.picture = m.picture;
      } else {
        chip.icon = "mdi:account";
        chip.icon_color = m.color;
      }
      chips.push(chip);
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

    // Signature so we don't rebuild card every hass tick
    const sig = JSON.stringify({
      m: members.map((m) => [m.name, m.color, m.picture]),
      f: currentFilter,
      cfg: this._config.extra_chips.length,
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
}

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
