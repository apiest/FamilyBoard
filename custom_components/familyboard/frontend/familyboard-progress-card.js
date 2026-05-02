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
    // Per-member "was already at 100% on the last render" flag, so we
    // only celebrate the *transition* to full and reset when the day
    // rolls over (total resets).
    this._lastFull = new Map();
    // Per-member "currently celebrating" flag — protects against the
    // animation re-triggering on every coordinator tick while still 100%.
    this._celebrating = new Set();
    this._lastSig = "";
  }

  setConfig(config) {
    this._config = {
      entity: config.entity || "sensor.familyboard_progress",
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render when the progress sensor (or its members payload)
    // actually changed. Otherwise unrelated state updates would wipe an
    // in-flight confetti animation.
    const stateObj = hass && this._config.entity
      ? hass.states[this._config.entity]
      : null;
    const sig = stateObj
      ? `${stateObj.state}|${JSON.stringify(stateObj.attributes.members || [])}`
      : "";
    if (sig !== this._lastSig) {
      this._lastSig = sig;
      this._render();
    }
    this._maybeCelebrate();
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
        border-radius: var(--ha-card-border-radius, 20px);
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
        font-size: 0.95em;
        color: var(--primary-text-color, #e6edf3);
        font-weight: 500;
        text-align: center;
      }
      .member-count {
        font-size: 0.85em;
        color: var(--secondary-text-color, #8b949e);
      }
      .member-presence {
        font-size: 0.8em;
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
      /* --- Reward animation: triggered on the transition to 100%. --- */
      .ring-container.celebrate svg {
        animation: fb-ring-pulse 0.6s ease-out 2;
      }
      .ring-container.celebrate .ring-fg {
        filter: drop-shadow(0 0 8px var(--fb-celebrate-color, #ffd166));
      }
      @keyframes fb-ring-pulse {
        0%   { transform: rotate(-90deg) scale(1); }
        50%  { transform: rotate(-90deg) scale(1.12); }
        100% { transform: rotate(-90deg) scale(1); }
      }
      .confetti {
        position: absolute;
        top: 50%;
        left: 50%;
        width: 8px;
        height: 8px;
        border-radius: 2px;
        pointer-events: none;
        opacity: 0;
        will-change: transform, opacity;
        animation: fb-confetti 1.4s ease-out forwards;
      }
      @keyframes fb-confetti {
        0%   { transform: translate(-50%, -50%) rotate(0deg); opacity: 1; }
        100% {
          transform:
            translate(calc(-50% + var(--fb-dx, 40px)),
                      calc(-50% + var(--fb-dy, -40px)))
            rotate(var(--fb-rot, 360deg));
          opacity: 0;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .ring-container.celebrate svg { animation: none; }
        .confetti { display: none; }
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
            <div class="ring-container" data-member="${this._escAttr(m.name || "")}" style="--fb-celebrate-color:${this._escAttr(color)}">
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

  _maybeCelebrate() {
    if (!this._hass || !this._config.entity) return;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) return;
    const members = stateObj.attributes.members || [];
    const seen = new Set();
    for (const m of members) {
      const name = m.name || "";
      if (!name) continue;
      seen.add(name);
      const total = m.total || 0;
      const completed = m.completed || 0;
      const isFull = total > 0 && completed >= total;
      const wasFull = this._lastFull.get(name) === true;
      this._lastFull.set(name, isFull);
      if (isFull && !wasFull && !this._celebrating.has(name)) {
        this._celebrate(name, m.color || "#4A90D9");
      }
    }
    // Drop tracking for members no longer in the sensor (config change).
    for (const name of Array.from(this._lastFull.keys())) {
      if (!seen.has(name)) this._lastFull.delete(name);
    }
  }

  _celebrate(name, color) {
    const root = this.shadowRoot;
    if (!root) return;
    const container = root.querySelector(
      `.ring-container[data-member="${CSS.escape(name)}"]`,
    );
    if (!container) return;
    this._celebrating.add(name);
    container.classList.add("celebrate");

    // Spawn ~16 confetti dots with randomized trajectories.
    const palette = [color, "#FFD166", "#A8C8EC", "#B5E0C2", "#F4C2D7"];
    const dots = [];
    for (let i = 0; i < 16; i++) {
      const dot = document.createElement("span");
      dot.className = "confetti";
      const angle = Math.random() * Math.PI * 2;
      const distance = 32 + Math.random() * 28;
      const dx = Math.cos(angle) * distance;
      const dy = Math.sin(angle) * distance;
      const rot = (Math.random() * 720 - 360).toFixed(0);
      dot.style.setProperty("--fb-dx", `${dx.toFixed(0)}px`);
      dot.style.setProperty("--fb-dy", `${dy.toFixed(0)}px`);
      dot.style.setProperty("--fb-rot", `${rot}deg`);
      dot.style.background = palette[i % palette.length];
      dot.style.animationDelay = `${(Math.random() * 0.15).toFixed(2)}s`;
      container.appendChild(dot);
      dots.push(dot);
    }

    setTimeout(() => {
      container.classList.remove("celebrate");
      for (const d of dots) d.remove();
      this._celebrating.delete(name);
    }, 1800);
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

  static async getConfigElement() {
    await customElements.whenDefined("ha-form");
    return document.createElement("familyboard-progress-card-editor");
  }
}

const PROGRESS_EDITOR_SCHEMA = [
  {
    name: "entity",
    required: true,
    selector: { entity: { domain: "sensor" } },
  },
];

class FamilyBoardProgressCardEditor extends HTMLElement {
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
      this._form.schema = PROGRESS_EDITOR_SCHEMA;
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

customElements.define("familyboard-progress-card-editor", FamilyBoardProgressCardEditor);
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
