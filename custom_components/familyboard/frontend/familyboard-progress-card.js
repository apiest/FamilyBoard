/**
 * FamilyBoard Progress Card
 *
 * Standalone Lovelace card showing per-member chore progress as
 * circular rings with member colors, pictures, and completed/total counts.
 *
 * Config:
 *   type: custom:familyboard-progress-card
 *   entity: sensor.familyboard_progress
 */

class FamilyBoardProgressCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
  }

  setConfig(config) {
    this._config = {
      entity: config.entity || "sensor.familyboard_progress",
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config.entity) return;

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<div style="padding:16px;color:var(--secondary-text-color)">Waiting for ${this._esc(this._config.entity)}...</div>`;
      return;
    }

    const members = stateObj.attributes.members || [];

    const style = `
      :host {
        display: block;
      }
      .card {
        padding: 16px;
        background: var(--ha-card-background, var(--card-background-color, rgba(255,255,255,0.04)));
        border-radius: var(--ha-card-border-radius, 16px);
        border: 1px solid var(--ha-card-border-color, rgba(255,255,255,0.06));
      }
      .progress-grid {
        display: flex;
        justify-content: center;
        gap: 24px;
        flex-wrap: wrap;
      }
      .member-progress {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        min-width: 80px;
      }
      .ring-container {
        position: relative;
        width: 64px;
        height: 64px;
      }
      .ring-container svg {
        width: 64px;
        height: 64px;
        transform: rotate(-90deg);
      }
      .ring-bg {
        fill: none;
        stroke: rgba(255,255,255,0.08);
        stroke-width: 5;
      }
      .ring-fg {
        fill: none;
        stroke-width: 5;
        stroke-linecap: round;
        transition: stroke-dashoffset 0.5s ease;
      }
      .ring-picture {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 40px;
        height: 40px;
        border-radius: 50%;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .ring-picture img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .ring-picture .initial {
        font-size: 18px;
        font-weight: 700;
        color: white;
      }
      .member-name {
        font-size: 0.85em;
        color: var(--primary-text-color, #e6edf3);
        font-weight: 500;
        text-align: center;
      }
      .member-count {
        font-size: 0.75em;
        color: var(--secondary-text-color, #8b949e);
      }
      .member-presence {
        font-size: 0.7em;
        color: var(--secondary-text-color, #8b949e);
        text-transform: capitalize;
        opacity: 0.85;
      }
      .member-presence.home {
        color: var(--success-color, #4caf50);
      }
      .member-presence.away {
        color: var(--warning-color, #ff9800);
      }
      .empty {
        color: var(--secondary-text-color, #8b949e);
        font-size: 0.95em;
        text-align: center;
        padding: 12px 0;
      }
    `;

    let html = `<style>${style}</style><div class="card">`;

    if (members.length === 0) {
      html += `<div class="empty">Geen leden</div>`;
    } else {
      html += `<div class="progress-grid">`;
      for (const m of members) {
        const total = m.total || 0;
        const completed = m.completed || 0;
        const pct = m.percentage || 0;
        const color = m.color || "#4A90D9";
        const radius = 27;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference - (pct / 100) * circumference;

        const initial = (m.name || "?")[0].toUpperCase();
        const pictureHtml = m.picture
          ? `<img src="${this._escAttr(m.picture)}" alt="${this._esc(initial)}">`
          : `<span class="initial" style="color:${this._escAttr(color)}">${this._esc(initial)}</span>`;

        const presence = this._presenceFor(m.person);
        const presenceHtml = presence
          ? `<div class="member-presence ${presence.cls}">${this._esc(presence.label)}</div>`
          : "";

        html += `
          <div class="member-progress">
            <div class="ring-container">
              <svg viewBox="0 0 64 64">
                <circle class="ring-bg" cx="32" cy="32" r="${radius}" />
                <circle class="ring-fg" cx="32" cy="32" r="${radius}"
                  stroke="${this._escAttr(color)}"
                  stroke-dasharray="${circumference}"
                  stroke-dashoffset="${offset}" />
              </svg>
              <div class="ring-picture">${pictureHtml}</div>
            </div>
            <div class="member-name">${this._esc(m.name || "")}</div>
            ${presenceHtml}
            <div class="member-count">${completed} / ${total}</div>
          </div>
        `;
      }
      html += `</div>`;
    }

    html += `</div>`;
    this.shadowRoot.innerHTML = html;
  }

  _presenceFor(personEntity) {
    if (!personEntity || !this._hass) return null;
    const st = this._hass.states[personEntity];
    if (!st) return null;
    const raw = st.state;
    // Try to localize via hass; fall back to a Dutch mapping for common states
    const dutch = { home: "Thuis", not_home: "Afwezig", unknown: "Onbekend", unavailable: "Onbeschikbaar" };
    let label = dutch[raw];
    if (!label && this._hass.localize) {
      label = this._hass.localize(`state.person.${raw}`)
        || this._hass.localize(`component.person.entity_component._.state.${raw}`);
    }
    if (!label) label = raw;
    let cls = "";
    if (raw === "home") cls = "home";
    else if (raw === "not_home") cls = "away";
    return { label, cls };
  }

  _esc(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  _escAttr(str) {
    return String(str).replace(/[&"'<>]/g, (c) => ({
      "&": "&amp;",
      '"': "&quot;",
      "'": "&#39;",
      "<": "&lt;",
      ">": "&gt;",
    })[c]);
  }

  getCardSize() {
    return 2;
  }

  getGridOptions() {
    return { rows: 2, columns: 12, min_rows: 2, max_rows: 2 };
  }

  static getStubConfig() {
    return {
      entity: "sensor.familyboard_progress",
    };
  }
}

customElements.define("familyboard-progress-card", FamilyBoardProgressCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-progress-card")) {
  window.customCards.push({
    type: "familyboard-progress-card",
    name: "FamilyBoard Progress",
    description: "Per-member chore progress rings with colors and pictures",
    documentationURL: "https://github.com/apiest/FamilyBoard#lovelace-cards",
    preview: false,
  });
}
