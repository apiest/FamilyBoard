/**
 * FamilyBoard Category Card
 *
 * Auto-discovers `switch.familyboard_category_*` entities and renders one
 * mushroom chip per category. Tapping a chip toggles that switch, which
 * the calendar card uses to filter events by category.
 *
 * Config:
 *   type: custom:familyboard-category-card
 *   color: amber                 # optional, color when switch is on
 *   alignment: start|center|end  # optional
 *   prefix: switch.familyboard_category_  # optional override
 */

const DEFAULT_PREFIX = "switch.familyboard_category_";

const CHIP_STYLE = `
  ha-card {
    --chip-font-size: 0.95rem;
    --chip-font-weight: 600;
    --chip-icon-size: 1.4rem;
    --chip-height: 40px;
    --chip-padding: 0 12px;
  }
`;

class FamilyBoardCategoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._inner = null;
    this._lastSig = "";
  }

  setConfig(config) {
    this._config = {
      color: config.color || "amber",
      alignment: config.alignment || "start",
      prefix: config.prefix || DEFAULT_PREFIX,
    };
    this._lastSig = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 1;
  }

  static getStubConfig() {
    return {};
  }

  _switches() {
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter((id) => id.startsWith(this._config.prefix))
      .sort();
  }

  _label(stateObj) {
    const name = stateObj?.attributes?.friendly_name || "";
    // Strip the leading "FamilyBoard " prefix that `_attr_has_entity_name`
    // bolts on, so chips show just the category name.
    return name.replace(/^FamilyBoard\s+/i, "") || stateObj?.entity_id || "";
  }

  async _render() {
    if (!this._hass) return;
    const switches = this._switches();
    const sig = switches
      .map((id) => `${id}:${this._hass.states[id]?.state}`)
      .join("|");
    if (sig === this._lastSig && this._inner) {
      this._inner.hass = this._hass;
      return;
    }
    this._lastSig = sig;

    if (!switches.length) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    const chips = switches.map((swid) => {
      const sw = this._hass.states[swid];
      const on = sw && sw.state === "on";
      return {
        type: "template",
        icon: on ? "mdi:calendar-check" : "mdi:calendar-remove",
        icon_color: on ? this._config.color : "grey",
        content: this._label(sw),
        tap_action: {
          action: "perform-action",
          perform_action: "switch.toggle",
          target: { entity_id: swid },
        },
      };
    });

    const cardConfig = {
      type: "custom:mushroom-chips-card",
      alignment: this._config.alignment,
      chips,
      card_mod: { style: CHIP_STYLE },
    };

    let helpers;
    try {
      helpers = await window.loadCardHelpers();
    } catch (_e) {
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

customElements.define("familyboard-category-card", FamilyBoardCategoryCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "familyboard-category-card",
  name: "FamilyBoard Category Filter",
  description:
    "Auto-discovered chip toggles for FamilyBoard calendar categories.",
});
