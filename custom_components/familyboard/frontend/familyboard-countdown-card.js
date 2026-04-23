/**
 * FamilyBoard Countdown Card
 *
 * Renders a single editable countdown to a target date, e.g.
 * "⏳ Nog 12 dagen tot Zomervakantie!". Reads two FamilyBoard entities
 * (`text.familyboard_countdown_label` + `datetime.familyboard_countdown_date`)
 * and edits them in place via `text.set_value` / `datetime.set_value`, so
 * the kiosk user can update the countdown without admin login.
 *
 * Config:
 *   type: custom:familyboard-countdown-card
 *   label_entity: text.familyboard_countdown_label    # optional
 *   date_entity:  datetime.familyboard_countdown_date # optional
 *   editable: true                                    # optional, default true
 *
 * Behaviour:
 * - Hidden when label is empty.
 * - `> 1` → "⏳ Nog N dagen tot LABEL!"
 * - `1`   → "⏳ Morgen is het LABEL!"
 * - `0`   → "🎉 Vandaag is het LABEL!"
 * - `< 0` → card auto-clears the label once (idempotent), then hides.
 * - Re-renders on entity state change AND every 60s for the day rollover.
 */

const DEFAULT_LABEL_ENTITY = "text.familyboard_countdown_label";
const DEFAULT_DATE_ENTITY = "datetime.familyboard_countdown_date";

/**
 * Format the visible countdown line. Pure function, exported for tests.
 * Returns "" when there's nothing to render (no label or expired).
 */
export function formatCountdown(label, daysRemaining) {
  const trimmed = (label || "").trim();
  if (!trimmed) return "";
  if (daysRemaining > 1) return `⏳ Nog ${daysRemaining} dagen tot ${trimmed}!`;
  if (daysRemaining === 1) return `⏳ Morgen is het ${trimmed}!`;
  if (daysRemaining === 0) return `🎉 Vandaag is het ${trimmed}!`;
  return "";
}

/**
 * Compute days between today (local) and an ISO datetime string. Returns
 * null when the date can't be parsed.
 */
export function daysUntil(targetIso, now = new Date()) {
  if (!targetIso) return null;
  const target = new Date(targetIso);
  if (Number.isNaN(target.getTime())) return null;
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const b = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  return Math.round((b - a) / 86400000);
}

class FamilyBoardCountdownCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._editing = false;
    this._cleared = null; // entity_id+date_iso we last auto-cleared for
    this._tick = null;
  }

  setConfig(config) {
    this._config = {
      label_entity: (config && config.label_entity) || DEFAULT_LABEL_ENTITY,
      date_entity: (config && config.date_entity) || DEFAULT_DATE_ENTITY,
      editable: config && config.editable === false ? false : true,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._maybeAutoClear();
    this._render();
  }

  connectedCallback() {
    if (this._tick) return;
    this._tick = setInterval(() => this._render(), 60_000);
  }

  disconnectedCallback() {
    if (this._tick) {
      clearInterval(this._tick);
      this._tick = null;
    }
  }

  getCardSize() {
    return 1;
  }

  static getStubConfig() {
    return {
      label_entity: DEFAULT_LABEL_ENTITY,
      date_entity: DEFAULT_DATE_ENTITY,
    };
  }

  _readState() {
    if (!this._hass) return { label: "", dateIso: null };
    const ls = this._hass.states[this._config.label_entity];
    const ds = this._hass.states[this._config.date_entity];
    const label = ls && ls.state && !["unknown", "unavailable"].includes(ls.state) ? ls.state : "";
    const dateIso = ds && ds.state && !["unknown", "unavailable"].includes(ds.state) ? ds.state : null;
    return { label, dateIso };
  }

  _maybeAutoClear() {
    if (!this._hass) return;
    const { label, dateIso } = this._readState();
    if (!label.trim() || !dateIso) return;
    const days = daysUntil(dateIso);
    if (days === null || days >= 0) return;
    const sig = `${this._config.label_entity}|${dateIso}`;
    if (this._cleared === sig) return;
    this._cleared = sig;
    this._hass.callService("text", "set_value", { value: "" }, { entity_id: this._config.label_entity });
  }

  _render() {
    if (!this._hass) return;

    const { label, dateIso } = this._readState();
    const days = daysUntil(dateIso);
    const text = formatCountdown(label, days ?? -1);

    // Hidden when nothing to show AND not currently editing.
    if (!text && !this._editing) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    if (this._editing) {
      this._renderEditor(label, dateIso);
      return;
    }

    this._renderDisplay(text);
  }

  _renderDisplay(text) {
    const editable = this._config.editable !== false;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card {
          padding: 14px 16px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .text {
          flex: 1;
          font-size: 1.15em;
          line-height: 1.3;
        }
        button.gear {
          background: none;
          border: none;
          color: var(--secondary-text-color);
          cursor: pointer;
          padding: 4px;
          font-size: 1.1em;
        }
        button.gear:hover { color: var(--primary-text-color); }
      </style>
      <ha-card>
        <div class="text">${this._esc(text)}</div>
        ${editable ? `<button class="gear" title="Aanpassen" aria-label="Aanpassen">⚙️</button>` : ""}
      </ha-card>
    `;
    if (editable) {
      const btn = this.shadowRoot.querySelector("button.gear");
      if (btn) btn.addEventListener("click", () => this._enterEdit());
    }
  }

  _renderEditor(label, dateIso) {
    const dateOnly = dateIso ? dateIso.slice(0, 10) : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 14px 16px; }
        form { display: flex; flex-direction: column; gap: 10px; }
        label { font-size: 0.9em; color: var(--secondary-text-color); }
        input {
          padding: 6px 8px;
          font: inherit;
          color: var(--primary-text-color);
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 4px;
        }
        .row { display: flex; gap: 8px; justify-content: flex-end; }
        button {
          padding: 6px 12px;
          font: inherit;
          cursor: pointer;
          background: var(--primary-color);
          color: var(--text-primary-color);
          border: none;
          border-radius: 4px;
        }
        button.secondary {
          background: transparent;
          color: var(--secondary-text-color);
          border: 1px solid var(--divider-color);
        }
      </style>
      <ha-card>
        <form>
          <label for="cd-label">Label</label>
          <input id="cd-label" type="text" maxlength="80" value="${this._esc(label)}" placeholder="Bv. Zomervakantie" />
          <label for="cd-date">Datum</label>
          <input id="cd-date" type="date" value="${this._esc(dateOnly)}" />
          <div class="row">
            <button type="button" class="secondary" data-act="cancel">Annuleer</button>
            <button type="button" data-act="save">Opslaan</button>
          </div>
        </form>
      </ha-card>
    `;
    const labelEl = this.shadowRoot.getElementById("cd-label");
    const dateEl = this.shadowRoot.getElementById("cd-date");
    this.shadowRoot
      .querySelector('button[data-act="cancel"]')
      .addEventListener("click", () => this._exitEdit());
    this.shadowRoot
      .querySelector('button[data-act="save"]')
      .addEventListener("click", () => this._save(labelEl.value, dateEl.value));
    if (labelEl && labelEl.focus) {
      // Focus the label input for fast kiosk entry.
      setTimeout(() => labelEl.focus(), 0);
    }
  }

  _enterEdit() {
    this._editing = true;
    this._render();
  }

  _exitEdit() {
    this._editing = false;
    this._render();
  }

  async _save(rawLabel, rawDate) {
    if (!this._hass) return;
    const label = (rawLabel || "").trim();
    // Reset the cleared sentinel so the next render evaluates fresh.
    this._cleared = null;
    const calls = [
      this._hass.callService(
        "text",
        "set_value",
        { value: label },
        { entity_id: this._config.label_entity },
      ),
    ];
    if (rawDate) {
      // datetime.set_value expects a full ISO timestamp; pin to local midnight.
      const iso = `${rawDate}T00:00:00`;
      calls.push(
        this._hass.callService(
          "datetime",
          "set_value",
          { datetime: iso },
          { entity_id: this._config.date_entity },
        ),
      );
    }
    try {
      await Promise.all(calls);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("familyboard-countdown-card: save failed", e);
    }
    this._editing = false;
    this._render();
  }

  _esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  static async getConfigElement() {
    await customElements.whenDefined("ha-form");
    return document.createElement("familyboard-countdown-card-editor");
  }
}

const COUNTDOWN_EDITOR_SCHEMA = [
  {
    name: "label_entity",
    required: true,
    selector: { entity: { domain: "text" } },
  },
  {
    name: "date_entity",
    required: true,
    selector: { entity: { domain: "datetime" } },
  },
  { name: "editable", selector: { boolean: {} } },
];

class FamilyBoardCountdownCardEditor extends HTMLElement {
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
      this._form.schema = COUNTDOWN_EDITOR_SCHEMA;
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

customElements.define("familyboard-countdown-card-editor", FamilyBoardCountdownCardEditor);
customElements.define("familyboard-countdown-card", FamilyBoardCountdownCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-countdown-card")) {
  window.customCards.push({
    type: "familyboard-countdown-card",
    name: "FamilyBoard Countdown Card",
    description: "Editable countdown to a configurable target date.",
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
  `%c FAMILYBOARD-COUNTDOWN-CARD %c v${FB_VERSION} `,
  "color:white;background:#4A90D9;font-weight:bold;",
  "color:#4A90D9;background:transparent;",
);
