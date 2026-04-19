/**
 * FamilyBoard Chores Card
 *
 * Custom Lovelace card that displays chores as checkable items
 * with datetime, member badges, shared chore support, and view filtering.
 *
 * Config:
 *   type: custom:familyboard-chores-card
 *   entity: sensor.familyboard_chores
 *   filter_entity: select.familyboard_calendar
 *   view_entity: select.familyboard_view
 */

class FamilyBoardChoresCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._checkedItems = new Set();
    this._tickTimer = null;
  }

  connectedCallback() {
    // Re-render every 30s so "NU" badge appears/disappears as time passes
    if (!this._tickTimer) {
      this._tickTimer = setInterval(() => this._render(), 30000);
    }
  }

  disconnectedCallback() {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
      this._tickTimer = null;
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define an 'entity' for the chores card");
    }
    this._config = {
      entity: config.entity,
      filter_entity: config.filter_entity || null,
      view_entity: config.view_entity || "select.familyboard_view",
      member: config.member || null,
      members_entity: config.members_entity || "sensor.familyboard_members",
      show_header: config.show_header !== false,
      ...config,
    };
  }

  _isVisible() {
    // When member is configured, hide card if filter excludes that member
    if (!this._config.member) return true;
    if (!this._config.filter_entity || !this._hass) return true;
    const filterState = this._hass.states[this._config.filter_entity];
    if (!filterState) return true;
    const filter = filterState.state;
    if (filter === "Alles") return true;
    return filter === this._config.member;
  }

  _getMemberMeta(name) {
    if (!this._hass || !this._config.members_entity) return null;
    const stateObj = this._hass.states[this._config.members_entity];
    if (!stateObj) return null;
    const members = stateObj.attributes.members || [];
    return members.find((m) => m.name === name) || null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _getFilteredItems() {
    if (!this._hass || !this._config.entity) return [];

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) return [];

    let items = stateObj.attributes.items || [];

    // Apply view filter (date-based filtering)
    if (this._config.view_entity) {
      const viewState = this._hass.states[this._config.view_entity];
      if (viewState) {
        const view = viewState.state;
        items = this._filterByView(items, view);
      }
    }

    // Hard member filter: when card is bound to a member, always show only that member
    if (this._config.member) {
      const m = this._config.member;
      return items.filter((i) => {
        if (i.member === m) return true;
        if (i.shared && i.shared_members && i.shared_members.includes(m)) return true;
        return false;
      });
    }

    // Apply member filter from filter_entity
    if (this._config.filter_entity) {
      const filterState = this._hass.states[this._config.filter_entity];
      if (filterState) {
        const filter = filterState.state;
        if (filter === "Alles") {
          return items;
        }
        // Member filter: include personal chores + shared chores where member is listed
        return items.filter((i) => {
          if (i.member === filter) return true;
          if (i.shared && i.shared_members && i.shared_members.includes(filter)) return true;
          return false;
        });
      }
    }

    return items;
  }

  _filterByView(items, view) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let endDate = null;

    if (view === "Vandaag") {
      endDate = new Date(today);
    } else if (view === "Morgen") {
      endDate = new Date(today);
      endDate.setDate(endDate.getDate() + 1);
    } else if (view === "Week") {
      endDate = new Date(today);
      endDate.setDate(endDate.getDate() + 7);
    } else if (view === "2 Weken") {
      endDate = new Date(today);
      endDate.setDate(endDate.getDate() + 14);
    } else if (view === "Maand") {
      endDate = new Date(today);
      endDate.setDate(endDate.getDate() + 30);
    }

    if (!endDate) return items;

    return items.filter((item) => {
      if (!item.due) return true; // No due date → always shown
      try {
        const due = new Date(item.due + "T00:00:00");
        // Overdue items are always shown
        if (due < today) return true;
        return due <= endDate;
      } catch (e) {
        return true;
      }
    });
  }

  _formatTime(isoStr) {
    if (!isoStr) return null;
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString("nl-NL", {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (e) {
      return null;
    }
  }

  _formatDue(dueStr) {
    if (!dueStr) return null;
    try {
      const due = new Date(dueStr + "T00:00:00");
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const tomorrow = new Date(today);
      tomorrow.setDate(tomorrow.getDate() + 1);
      if (due.getTime() === today.getTime()) return "Vandaag";
      if (due.getTime() === tomorrow.getTime()) return "Morgen";
      return due.toLocaleDateString("nl-NL", { weekday: "short", day: "numeric", month: "short" });
    } catch (e) {
      return dueStr;
    }
  }

  _isOverdue(dueStr) {
    if (!dueStr) return false;
    try {
      const due = new Date(dueStr + "T00:00:00");
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      return due < today;
    } catch (e) {
      return false;
    }
  }

  _isDueToday(dueStr) {
    if (!dueStr) return false;
    try {
      const due = new Date(dueStr + "T00:00:00");
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      return due.getTime() === today.getTime();
    } catch (e) {
      return false;
    }
  }

  _isActive(startStr, endStr) {
    if (!startStr || !endStr) return false;
    try {
      const now = new Date();
      return new Date(startStr) <= now && now <= new Date(endStr);
    } catch (e) {
      return false;
    }
  }

  async _handleCheck(item) {
    if (!item.uid || !item.todo_entity || !this._hass) return;

    this._checkedItems.add(item.uid);
    this._render();

    try {
      await this._hass.callService("todo", "update_item", {
        item: item.uid,
        status: "completed",
      }, { entity_id: item.todo_entity });
      // Trigger coordinator refresh so progress updates immediately
      await this._hass.callService("homeassistant", "update_entity", {
        entity_id: this._config.entity,
      });
    } catch (err) {
      console.error("FamilyBoard: Failed to complete chore:", err);
      this._checkedItems.delete(item.uid);
      this._render();
    }
  }

  _render() {
    // Hide card entirely when member-bound and filter excludes this member
    if (!this._isVisible()) {
      this.shadowRoot.innerHTML = "";
      this.style.display = "none";
      return;
    }
    this.style.display = "";

    const items = this._getFilteredItems();
    const memberMeta = this._config.member ? this._getMemberMeta(this._config.member) : null;
    const memberColor = memberMeta?.color || "#4A90D9";
    const memberPic = memberMeta?.picture || "";

    // Determine "active member" for shared-chore badge override:
    // 1. Explicit `member` config wins
    // 2. Else, when filter_entity is set to a specific member name (not "Alles"), use that
    let activeMember = this._config.member || null;
    let activeMemberMeta = memberMeta;
    if (!activeMember && this._config.filter_entity) {
      const fs = this._hass.states[this._config.filter_entity];
      if (fs && fs.state && fs.state !== "Alles") {
        activeMember = fs.state;
        activeMemberMeta = this._getMemberMeta(activeMember);
      }
    }
    const activeColor = activeMemberMeta?.color || memberColor;
    const activePic = activeMemberMeta?.picture || memberPic;

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
      .empty {
        color: var(--secondary-text-color, #8b949e);
        font-size: 0.95em;
        text-align: center;
        padding: 12px 0;
      }
      .task-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .task-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 4px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        transition: opacity 0.3s ease;
      }
      .task-row:last-child {
        border-bottom: none;
      }
      .task-row.checked {
        opacity: 0.35;
      }
      .task-row.checked .task-summary {
        text-decoration: line-through;
      }
      .checkbox {
        width: 22px;
        height: 22px;
        border-radius: 50%;
        border: 2px solid var(--secondary-text-color, #8b949e);
        cursor: pointer;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s ease;
        background: transparent;
      }
      .checkbox:hover {
        border-color: var(--primary-color, #4A90D9);
        background: rgba(74, 144, 217, 0.15);
      }
      .checkbox.checked {
        border-color: var(--primary-color, #4A90D9);
        background: var(--primary-color, #4A90D9);
      }
      .checkbox.checked::after {
        content: "✓";
        color: white;
        font-size: 13px;
        font-weight: bold;
      }
      .checkbox.disabled {
        opacity: 0.3;
        cursor: default;
        pointer-events: none;
      }
      .badge {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 700;
        color: white;
        flex-shrink: 0;
        text-transform: uppercase;
      }
      .badge img {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        object-fit: cover;
      }
      .task-content {
        flex: 1;
        min-width: 0;
      }
      .task-summary {
        color: var(--primary-text-color, #e6edf3);
        font-size: 1em;
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .task-time {
        color: var(--secondary-text-color, #8b949e);
        font-size: 0.82em;
        margin-top: 1px;
      }
      .task-desc {
        color: var(--secondary-text-color, #8b949e);
        font-size: 0.82em;
        margin-top: 2px;
        opacity: 0.8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .task-time.overdue {
        color: #E74C3C;
        font-weight: 600;
      }
      .task-row.active {
        background: color-mix(in srgb, var(--fb-color, #4A90D9) 18%, transparent);
        border-radius: 10px;
        border-bottom: none;
        padding: 10px 8px;
        box-shadow: 0 0 0 2px color-mix(in srgb, var(--fb-color, #4A90D9) 60%, transparent);
      }
      .task-row.active .task-summary {
        font-weight: 700;
        color: #fff;
      }
      .task-row.active .task-time {
        color: var(--fb-color, #6aafef);
        font-weight: 600;
      }
      .live-pill {
        display: inline-block;
        background: var(--fb-color, #E74C3C);
        color: white;
        font-size: 0.7em;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 8px;
        margin-left: 6px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        vertical-align: middle;
      }
      .shared-indicator {
        display: inline-block;
        font-size: 0.75em;
        color: var(--secondary-text-color, #8b949e);
        margin-left: 6px;
        vertical-align: middle;
        opacity: 0.8;
      }
      .member-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 4px 4px 12px 4px;
        margin-bottom: 8px;
        border-bottom: 2px solid var(--fb-member-color, #4A90D9);
      }
      .member-header .avatar {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: 2px solid var(--fb-member-color, #4A90D9);
        overflow: hidden;
        flex-shrink: 0;
        background: var(--fb-member-color, #4A90D9);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 700;
      }
      .member-header .avatar img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .member-header .name {
        font-size: 1.1em;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .member-header .count {
        margin-left: auto;
        font-size: 0.85em;
        color: var(--secondary-text-color, #8b949e);
      }
    `;

    let html = `<style>${style}</style><div class="card" style="--fb-member-color: ${this._escAttr(memberColor)}">`;

    if (this._config.member && this._config.show_header) {
      const initial = (this._config.member || "?")[0];
      const avatar = memberPic
        ? `<img src="${this._escAttr(memberPic)}" alt="${this._esc(initial)}">`
        : this._esc(initial);
      html += `
        <div class="member-header">
          <div class="avatar">${avatar}</div>
          <div class="name">${this._esc(this._config.member)}</div>
          <div class="count">${items.length} ${items.length === 1 ? "taak" : "taken"}</div>
        </div>
      `;
    }

    if (items.length === 0) {
      html += `<div class="empty">Geen taken</div>`;
    } else {
      html += `<div class="task-list">`;
      for (const item of items) {
        const isChecked = this._checkedItems.has(item.uid);
        const canCheck = item.uid && item.todo_entity;
        let rowClass = isChecked ? "task-row checked" : "task-row";
        if (!isChecked && this._isActive(item.start, item.end)) rowClass += " active";
        const checkboxClass = isChecked
          ? "checkbox checked"
          : canCheck
            ? "checkbox"
            : "checkbox disabled";

        const startTime = this._formatTime(item.start);
        const endTime = this._formatTime(item.end);
        const dueStr = this._formatDue(item.due);
        const overdue = this._isOverdue(item.due);
        const isToday = this._isDueToday(item.due);
        const isActive = !isChecked && this._isActive(item.start, item.end);

        // Build display: time + date (skip date if today)
        let timeStr = "";
        if (startTime && endTime) {
          timeStr = `${startTime} – ${endTime}`;
        } else if (startTime) {
          timeStr = startTime;
        }
        if (dueStr && !isToday) {
          timeStr = timeStr ? `${timeStr} · 📅 ${dueStr}` : `📅 ${dueStr}`;
        }
        const timeClass = overdue ? "task-time overdue" : "task-time";

        const initial = (item.member || "?")[0];
        const pic = item.picture || "";
        // For shared chores when an active member is known, show that member's avatar/color
        let badgeColor = item.color || "#4A90D9";
        let badgePic = pic;
        let badgeInitial = initial;
        if (item.shared && activeMember) {
          badgeColor = activeColor;
          badgePic = activePic;
          badgeInitial = (activeMember || "?")[0];
        }
        const badgeContent = badgePic
          ? `<img src="${this._escAttr(badgePic)}" alt="${this._esc(badgeInitial)}">`
          : this._esc(badgeInitial);
        const desc = item.description || "";
        const sharedHtml = item.shared ? '<span class="shared-indicator">👥</span>' : '';

        html += `
          <div class="${rowClass}" data-uid="${item.uid || ""}" style="--fb-color: ${this._escAttr(item.color || "#4A90D9")}">
            <div class="${checkboxClass}" data-uid="${item.uid || ""}" data-todo="${item.todo_entity || ""}"></div>
            <div class="badge" style="background: ${this._escAttr(badgeColor)}">${badgeContent}</div>
            <div class="task-content">
              <div class="task-summary">${this._esc(item.summary || "")}${isActive ? '<span class="live-pill">NU</span>' : ''}${sharedHtml}</div>
              ${timeStr ? `<div class="${timeClass}">${overdue ? "⚠️ " : ""}${this._esc(timeStr)}</div>` : ""}
              ${desc ? `<div class="task-desc">${this._esc(desc)}</div>` : ""}
            </div>
          </div>
        `;
      }
      html += `</div>`;
    }

    html += `</div>`;
    this.shadowRoot.innerHTML = html;

    // Attach click handlers to checkboxes
    this.shadowRoot.querySelectorAll(".checkbox:not(.disabled):not(.checked)").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const uid = el.dataset.uid;
        const todoEntity = el.dataset.todo;
        if (!uid || !todoEntity) return;

        const items = this._getFilteredItems();
        const item = items.find((i) => i.uid === uid);
        if (item) this._handleCheck(item);
      });
    });
  }

  _esc(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  _escAttr(str) {
    return str.replace(/[&"'<>]/g, (c) => ({
      "&": "&amp;",
      '"': "&quot;",
      "'": "&#39;",
      "<": "&lt;",
      ">": "&gt;",
    })[c]);
  }

  getCardSize() {
    if (!this._isVisible()) return 0;
    return 3;
  }

  getGridOptions() {
    return { rows: 4, columns: 6, min_rows: 2 };
  }

  static getStubConfig() {
    return {
      entity: "sensor.familyboard_chores",
      filter_entity: "select.familyboard_calendar",
      view_entity: "select.familyboard_view",
      members_entity: "sensor.familyboard_members",
    };
  }
}

customElements.define("familyboard-chores-card", FamilyBoardChoresCard);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "familyboard-chores-card")) {
  window.customCards.push({
    type: "familyboard-chores-card",
    name: "FamilyBoard Chores",
    description: "Displays chores as checkable items with datetime, member badges, and shared chore support",
    documentationURL: "https://github.com/apiest/FamilyBoard#lovelace-cards",
    preview: false,
  });
}
