/**
 * FamilyBoard Recent Chores Card
 *
 * Shows the most recent chore completions logged by the coordinator
 * (Phase 5). Reads `sensor.familyboard_recent_chores.attributes.entries`
 * — newest first — and renders a chronological list with a member
 * avatar dot, summary, source badge and a relative timestamp.
 *
 * Unclaimed shared chores (member=null) are tagged "Gedeeld" with a
 * neutral dot.
 *
 * Config:
 *   type: custom:familyboard-recent-chores-card
 *   entity: sensor.familyboard_recent_chores      # optional
 *   members_entity: sensor.familyboard_progress   # for color lookup
 *   max: 25                                       # rows to display
 *   title: "Recent afgevinkt"                     # optional
 */

class FamilyBoardRecentChoresCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._lastSig = "";
  }

  setConfig(config) {
    this._config = {
      entity: config.entity || "sensor.familyboard_recent_chores",
      members_entity: config.members_entity || "sensor.familyboard_progress",
      max: Number.isFinite(config.max) ? Math.max(1, config.max) : 25,
      title: config.title ?? "Recent afgevinkt",
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const sig = st
      ? `${st.state}|${(st.attributes.entries || []).length}|${(st.attributes.entries || [])[0]?.ts || ""}`
      : "missing";
    if (sig !== this._lastSig) {
      this._lastSig = sig;
      this._render();
    }
  }

  getCardSize() {
    return 4;
  }

  _esc(s) {
    return String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  }

  _memberColors() {
    const out = new Map();
    const st = this._hass?.states?.[this._config.members_entity];
    const list = st?.attributes?.members || [];
    for (const m of list) {
      if (m && m.name) out.set(m.name, m.color || "var(--primary-color)");
    }
    return out;
  }

  _formatRelative(ts) {
    if (!ts) return "";
    const then = new Date(ts);
    if (Number.isNaN(then.getTime())) return "";
    const diffSec = Math.floor((Date.now() - then.getTime()) / 1000);
    if (diffSec < 45) return "net";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min geleden`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} u geleden`;
    const diffDays = Math.floor(diffSec / 86400);
    if (diffDays === 1) return "gisteren";
    if (diffDays < 7) return `${diffDays} dagen geleden`;
    return then.toLocaleDateString("nl-NL", {
      day: "numeric",
      month: "short",
    });
  }

  _render() {
    if (!this._hass) return;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<div style="padding:16px;color:var(--secondary-text-color)">Waiting for ${this._esc(this._config.entity)}...</div>`;
      return;
    }
    const all = stateObj.attributes.entries || [];
    const entries = all.slice(0, this._config.max);
    const colors = this._memberColors();

    const style = `
      :host { display:block; }
      .card {
        padding: 16px;
        background: var(--ha-card-background, var(--card-background-color, rgba(255,255,255,0.04)));
        border-radius: var(--ha-card-border-radius, 20px);
        border: 1px solid var(--ha-card-border-color, rgba(255,255,255,0.06));
      }
      h3.title {
        margin: 0 0 12px;
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .empty {
        padding: 24px 8px;
        text-align: center;
        color: var(--secondary-text-color);
        font-size: 0.95rem;
      }
      ul.list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      li.row {
        display: grid;
        grid-template-columns: 28px 1fr auto;
        align-items: center;
        gap: 12px;
        padding: 6px 8px;
        border-radius: 10px;
        background: rgba(255,255,255,0.02);
      }
      .dot {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        justify-self: center;
        box-shadow: 0 0 0 2px rgba(255,255,255,0.06);
      }
      .body {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
      }
      .summary {
        font-size: 0.95rem;
        color: var(--primary-text-color);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .meta {
        font-size: 0.78rem;
        color: var(--secondary-text-color);
      }
      .meta .badge {
        display: inline-block;
        padding: 1px 6px;
        margin-right: 6px;
        border-radius: 6px;
        background: rgba(255,255,255,0.06);
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .ts {
        font-size: 0.8rem;
        color: var(--secondary-text-color);
        white-space: nowrap;
      }
    `;

    let body;
    if (!entries.length) {
      body = `<div class="empty">Nog niets afgevinkt — succes! 💪</div>`;
    } else {
      const rows = entries
        .map((e) => {
          const member = e.member;
          const color = member
            ? colors.get(member) || "var(--primary-color)"
            : "var(--secondary-text-color)";
          const badge = e.source === "shared" ? "Gedeeld" : "Persoonlijk";
          const who = member ? this._esc(member) : "Niemand geclaimd";
          return `
            <li class="row">
              <span class="dot" style="background:${this._esc(color)}"></span>
              <div class="body">
                <span class="summary">${this._esc(e.summary || "")}</span>
                <span class="meta"><span class="badge">${this._esc(badge)}</span>${who}</span>
              </div>
              <span class="ts">${this._esc(this._formatRelative(e.ts))}</span>
            </li>
          `;
        })
        .join("");
      body = `<ul class="list">${rows}</ul>`;
    }

    const title = this._config.title
      ? `<h3 class="title">${this._esc(this._config.title)}</h3>`
      : "";

    this.shadowRoot.innerHTML = `
      <style>${style}</style>
      <div class="card">
        ${title}
        ${body}
      </div>
    `;
  }
}

if (!customElements.get("familyboard-recent-chores-card")) {
  customElements.define(
    "familyboard-recent-chores-card",
    FamilyBoardRecentChoresCard,
  );
}

window.customCards = window.customCards || [];
if (
  !window.customCards.find((c) => c.type === "familyboard-recent-chores-card")
) {
  window.customCards.push({
    type: "familyboard-recent-chores-card",
    name: "FamilyBoard Recent Chores",
    description: "Recent chore completions log (Phase 5).",
  });
}
