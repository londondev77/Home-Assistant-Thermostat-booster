/* Thermostat Boost Lovelace Card */
(() => {
  const VERSION = "0.9.4";
  const DOMAIN = "thermostat_boost";
  const CARD_TYPE = "thermostat-boost-card";
  const BOOST_TEMP_SUFFIX = "_boost_temperature";
  const BOOST_TIME_SUFFIX = "_boost_time_selector";
  const BOOST_ACTIVE_SUFFIX = "_boost_active";
  const BOOST_FINISH_SUFFIX = "_boost_finish";

  const computeLabel = (device) =>
    device?.name_by_user || device?.name || device?.id || "Thermostat Boost";

  const findEntityId = (entities, deviceId, suffix) => {
    const match = entities.find(
      (entry) => entry.device_id === deviceId && entry.entity_id.endsWith(suffix)
    );
    return match ? match.entity_id : null;
  };

  const findThermostatEntityId = (device) => {
    const identifiers = device?.identifiers || [];
    for (const identifier of identifiers) {
      if (identifier[0] === DOMAIN) {
        return identifier[1];
      }
    }
    return null;
  };

  const parseTimestamp = (value) => {
    if (!value || typeof value !== "string") return NaN;
    let iso = value.trim();
    if (iso.includes(" ") && !iso.includes("T")) {
      iso = iso.replace(" ", "T");
    }
    iso = iso.replace(/(\.\d{3})\d+/, "$1");
    let parsed = Date.parse(iso);
    if (Number.isNaN(parsed)) {
      parsed = Date.parse(value);
    }
    return parsed;
  };

  class ThermostatBoostCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._resolved = null;
      this._resolving = null;
      this._hass = null;
      this._helpers = null;
      this._bubbleHeaderCard = null;
      this._bubbleHeaderConfig = null;
      this._mainStack = null;
      this._mainStackConfig = null;
      this._bubbleHookTimer = null;
      this._bubbleCountdownTimer = null;

      const style = document.createElement("style");
      style.textContent = `
        .stack {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .message {
          padding: 12px;
          color: var(--secondary-text-color);
        }
      `;

      this._root = document.createElement("div");
      this._root.classList.add("stack");

      this._message = document.createElement("div");
      this._message.classList.add("message");

      this.shadowRoot.append(style, this._root);
    }

    static getConfigElement() {
      return document.createElement("thermostat-boost-card-editor");
    }

    static getStubConfig() {
      return { type: `custom:${CARD_TYPE}` };
    }

    setConfig(config) {
      this._config = { type: `custom:${CARD_TYPE}`, ...(config || {}) };
      window.__thermostatBoostCardLastConfig = this._config;
      this._resolved = null;
      this._resolving = null;
      this._root.innerHTML = "";
      this._root.appendChild(this._message);
      this._setMessage("Select a boost device in the card editor.");
      this._ensureResolved();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._bubbleHeaderCard) this._bubbleHeaderCard.hass = hass;
      if (this._mainStack) this._mainStack.hass = hass;
      this._ensureResolved();
    }

    disconnectedCallback() {
      if (this._bubbleHookTimer) {
        clearInterval(this._bubbleHookTimer);
        this._bubbleHookTimer = null;
      }
      if (this._bubbleCountdownTimer) {
        clearInterval(this._bubbleCountdownTimer);
        this._bubbleCountdownTimer = null;
      }
    }

    _setMessage(text) {
      this._message.textContent = text;
    }

    async _ensureResolved() {
      if (!this._hass) return;
      if (!this._config?.device_id && !this._config?.entity_id) return;
      if (this._resolved || this._resolving) return;

      this._resolving = this._config.device_id
        ? this._resolveFromDeviceId(this._hass, this._config.device_id)
        : this._resolveFromEntityId(this._hass, this._config.entity_id);
      const resolved = await this._resolving;
      this._resolving = null;

      if (!resolved) {
        this._setMessage("Unable to resolve the selected boost device.");
        window.__thermostatBoostCardLastResolved = null;
        return;
      }

      if (!resolved.thermostatEntityId) {
        this._setMessage("No linked thermostat found for this boost device.");
        return;
      }

      this._resolved = resolved;
      window.__thermostatBoostCardLastResolved = resolved;
      this._renderCards(resolved);
    }

    async _resolveFromEntityId(hass, entityId) {
      const entities = await hass.callWS({
        type: "config/entity_registry/list",
      });
      const entry = entities.find((item) => item.entity_id === entityId);
      if (!entry || !entry.device_id) return null;
      return this._resolveFromDeviceId(hass, entry.device_id, entities);
    }

    async _resolveFromDeviceId(hass, deviceId, entities = null) {
      const [devices, entityList] = await Promise.all([
        hass.callWS({ type: "config/device_registry/list" }),
        entities ? Promise.resolve(entities) : hass.callWS({ type: "config/entity_registry/list" }),
      ]);

      const device = devices.find((entry) => entry.id === deviceId);
      if (!device) return null;

      return {
        label: computeLabel(device),
        thermostatEntityId: findThermostatEntityId(device),
        boostTemperatureEntityId: findEntityId(
          entityList,
          deviceId,
          BOOST_TEMP_SUFFIX
        ),
        boostTimeEntityId: findEntityId(
          entityList,
          deviceId,
          BOOST_TIME_SUFFIX
        ),
        boostActiveEntityId: findEntityId(
          entityList,
          deviceId,
          BOOST_ACTIVE_SUFFIX
        ),
        boostFinishEntityId: findEntityId(
          entityList,
          deviceId,
          BOOST_FINISH_SUFFIX
        ),
      };
    }

    _renderCards(resolved) {
      const cards = [];

      const navSlug = (resolved.label || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
      const navAnchor = navSlug ? `#${navSlug}_detail` : "#detail";

      this._bubbleHeaderConfig = {
        type: "custom:bubble-card",
        card_type: "button",
        button_type: "state",
        name: resolved.label || "Thermostat",
        tap_action: {
          action: "navigate",
          navigation_path: navAnchor,
        },
        button_action: {
          tap_action: {
            action: "navigate",
            navigation_path: navAnchor,
          },
        },
        entity: resolved.thermostatEntityId,
        show_attribute: true,
        attribute: "current_temperature",
        show_state: false,
        icon: "mdi:desk",
        sub_button: {
          main: [
            {
              entity: resolved.boostFinishEntityId,
              name: "-",
              show_name: true,
              show_state: false,
              icon: "mdi:rocket-launch",
              show_background: true,
              tap_action: {
                action: "navigate",
                navigation_path: navAnchor,
              },
              visibility: [
                {
                  condition: "state",
                  entity: resolved.boostActiveEntityId,
                  state: "on",
                },
              ],
              fill_width: false,
            },
            {
              entity: resolved.thermostatEntityId,
              show_attribute: true,
              attribute: "temperature",
              show_icon: true,
              state_background: false,
              icon: "mdi:bullseye-arrow",
              tap_action: {
                action: "navigate",
                navigation_path: navAnchor,
              },
              fill_width: false,
              width: 79,
            },
            {
              icon: "mdi:fire",
              tap_action: {
                action: "navigate",
                url_path: navAnchor,
                navigation_path: navAnchor,
              },
              state_background: true,
            },
          ],
          bottom: [],
        },
        styles: `
          \${(() => {
            const state =
              card.querySelector('.bubble-sub-button-1 .bubble-sub-button-state') ||
              card.querySelector('.bubble-sub-button-1 .state') ||
              card.querySelector('.bubble-sub-button-1 [class*="state"]');
            if (state) {
              state.innerText = '-';
              state.style.fontSize = '11px';
              state.style.fontVariantNumeric = 'tabular-nums';
              state.style.lineHeight = '1.1';
            }
            return '';
          })()}
          .bubble-sub-button-1 .bubble-name {
            font-size: 11px;
            line-height: 1.1;
          }
          .bubble-sub-button-3 {
            background-color: \${hass.states['${resolved.thermostatEntityId}'].attributes.hvac_action === 'heating'
              ? 'var(--state-climate-heat-color)'
              : 'var(--card-background-color)'} !important;
          }
        `,
        slider_fill_orientation: "left",
        slider_value_position: "right",
      };

      cards.push({
        type: "custom:bubble-card",
        card_type: "pop-up",
        hash: navAnchor,
        name: resolved.label || "Thermostat",
        icon: "mdi:desk",
        show_header: true,
        button_type: "name",
        sub_button: {
          main: [],
          bottom: [],
        },
        slider_fill_orientation: "left",
        slider_value_position: "right",
      });

      cards.push({
        type: "thermostat",
        entity: resolved.thermostatEntityId,
        show_current_as_primary: true,
        features: [
          {
            type: "climate-preset-modes",
            style: "dropdown",
          },
        ],
      });

      if (resolved.boostTemperatureEntityId) {
        cards.push({
          type: "conditional",
          conditions: [
            {
              condition: "state",
              entity: resolved.boostActiveEntityId,
              state: "off",
            },
          ],
          card: {
            type: "vertical-stack",
            cards: [
              {
                type: "custom:slider-entity-row",
                entity: resolved.boostTemperatureEntityId,
                name: "Temperature",
                full_row: true,
                show_icon: true,
                max: 25,
                min: 5,
                step: 0.5,
                toggle: false,
                hide_state: false,
                icon: "mdi:thermometer",
              },
            ],
          },
        });
      }

      if (resolved.boostTimeEntityId) {
        cards.push({
          type: "conditional",
          conditions: [
            {
              condition: "state",
              entity: resolved.boostActiveEntityId,
              state: "off",
            },
          ],
          card: {
            type: "vertical-stack",
            cards: [
              {
                type: "custom:slider-entity-row",
                entity: resolved.boostTimeEntityId,
                name: "Boost Time",
                full_row: true,
                show_icon: true,
                toggle: false,
                hide_when_off: false,
                hide_state: false,
                icon: "mdi:av-timer",
              },
            ],
          },
        });
      }

      if (resolved.boostActiveEntityId && resolved.boostFinishEntityId) {
        cards.push({
          type: "conditional",
          conditions: [
            {
              condition: "state",
              entity: resolved.boostActiveEntityId,
              state: "on",
            },
          ],
          card: {
            type: "horizontal-stack",
            cards: [
              {
                type: "tile",
                entity: resolved.boostFinishEntityId,
                tap_action: {
                  action: "call-service",
                  service: `${DOMAIN}.finish_boost`,
                  service_data: {
                    entity_id: resolved.boostFinishEntityId,
                  },
                },
                color: "red",
                name: "Cancel Boost",
                hide_state: true,
                icon: "mdi:rocket",
              },
              {
                type: "custom:thermostat-boost-countdown",
                entity: resolved.boostFinishEntityId,
                name: "Boost Left",
                icon: "mdi:timer",
              },
            ],
          },
        });
      }

      if (resolved.boostTimeEntityId && resolved.boostFinishEntityId) {
        cards.push({
          type: "conditional",
          conditions: [
            {
              condition: "state",
              entity: resolved.boostActiveEntityId,
              state: "off",
            },
            {
              condition: "numeric_state",
              entity: resolved.boostTimeEntityId,
              above: 0.1,
            },
          ],
          card: {
            type: "horizontal-stack",
            cards: [
              {
                type: "tile",
                color: "green",
                name: "Start Boost",
                hide_state: true,
                vertical: false,
                icon: "mdi:rocket-launch",
                entity: resolved.boostFinishEntityId,
                tap_action: {
                  action: "call-service",
                  service: `${DOMAIN}.start_boost`,
                  service_data: {
                    entity_id: resolved.boostFinishEntityId,
                  },
                },
                icon_tap_action: {
                  action: "call-service",
                  service: `${DOMAIN}.start_boost`,
                  service_data: {
                    entity_id: resolved.boostFinishEntityId,
                  },
                },
              },
            ],
          },
        });
      }

      if (resolved.thermostatEntityId) {
        const thermostatName = resolved.label || resolved.thermostatEntityId;
        cards.push({
          type: "custom:scheduler-card",
          tags: [thermostatName],
          include: [resolved.thermostatEntityId],
          display_options: {
            primary_info: "{entity}",
            secondary_info: ["days"],
            icon: "entity",
          },
          discover_existing: false,
          grid_options: null,
          columns: 180,
          rows: "auto",
          title: false,
        });
      }

      this._mainStackConfig = {
        type: "vertical-stack",
        cards,
      };
      this._ensureMainStack();
    }

    async _getCardHelpers() {
      if (this._helpers) return this._helpers;
      if (!window.loadCardHelpers) return null;
      this._helpers = await window.loadCardHelpers();
      return this._helpers;
    }
    async _ensureMainStack() {
      if (!this._mainStackConfig) return;
      const helpers = await this._getCardHelpers();
      if (!helpers) return;
      const stackCard = await helpers.createCardElement(this._mainStackConfig);
      const bubbleCard = this._bubbleHeaderConfig
        ? await helpers.createCardElement(this._bubbleHeaderConfig)
        : null;
      this._root.innerHTML = "";
      if (bubbleCard) {
        this._root.append(bubbleCard);
        this._bubbleHeaderCard = bubbleCard;
        if (this._hass) this._bubbleHeaderCard.hass = this._hass;
      }
      this._root.append(stackCard);
      this._mainStack = stackCard;
      if (this._hass) this._mainStack.hass = this._hass;
    }

    _queryDeep(selector) {
      const stack = [this._root];
      while (stack.length > 0) {
        const node = stack.pop();
        if (!node) continue;
        if (node.querySelector) {
          const found = node.querySelector(selector);
          if (found) return found;
        }
        const children = node.children || [];
        for (let i = 0; i < children.length; i += 1) {
          stack.push(children[i]);
          if (children[i].shadowRoot) {
            stack.push(children[i].shadowRoot);
          }
        }
        if (node.shadowRoot) {
          stack.push(node.shadowRoot);
        }
      }
      return null;
    }

    _mountBubbleInlineCountdown() {
      if (!this._resolved?.boostFinishEntityId || !this._hass) return false;
      const subButton = this._queryDeep(".bubble-sub-button-1");
      if (!subButton) return false;

      return this._updateBubbleCountdownText();
    }

    _formatCountdown(entityId) {
      const stateObj = this._hass?.states?.[entityId];
      let finishIso = stateObj?.state;
      if (!finishIso || finishIso === "unknown" || finishIso === "unavailable") {
        finishIso = stateObj?.attributes?.end_time || null;
      }
      const finish = finishIso ? parseTimestamp(finishIso) : NaN;
      if (Number.isNaN(finish)) return "-";

      const now = Date.now();
      let remainingSec = Math.max(0, Math.floor((finish - now) / 1000));
      const hours = Math.floor(remainingSec / 3600);
      remainingSec -= hours * 3600;
      const minutes = Math.floor(remainingSec / 60);
      const seconds = remainingSec - minutes * 60;
      const hh = String(hours).padStart(2, "0");
      const mm = String(minutes).padStart(2, "0");
      const ss = String(seconds).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    }

    _queryDeepAll(selector) {
      const results = [];
      const visit = (node) => {
        if (!node) return;
        if (node.querySelectorAll) {
          const found = node.querySelectorAll(selector);
          for (let i = 0; i < found.length; i += 1) {
            results.push(found[i]);
          }
        }

        const children = node.children || [];
        for (let i = 0; i < children.length; i += 1) {
          visit(children[i]);
          if (children[i].shadowRoot) {
            visit(children[i].shadowRoot);
          }
        }
        if (node.shadowRoot) {
          visit(node.shadowRoot);
        }
      };

      visit(this._root);
      return results;
    }

    _updateBubbleCountdownText() {
      if (!this._resolved?.boostFinishEntityId || !this._hass) return false;
      let candidates = this._queryDeepAll(".bubble-sub-button-state");
      if (candidates.length === 0) {
        candidates = this._queryDeepAll(".bubble-sub-button .state");
      }
      if (candidates.length === 0) {
        candidates = this._queryDeepAll("[class*='sub-button'][class*='state']");
      }
      const stateObj = this._hass.states[this._resolved.boostFinishEntityId];
      const rawState = (stateObj?.state || "").trim();
      const rawEnd = (stateObj?.attributes?.end_time || "").trim();
      const datetimeHint = /\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}/;
      let container = null;
      for (let i = 0; i < candidates.length; i += 1) {
        const text = (candidates[i].textContent || "").trim();
        if (!text) continue;
        if (rawState && text.includes(rawState)) {
          container = candidates[i];
          break;
        }
        if (rawEnd && text.includes(rawEnd)) {
          container = candidates[i];
          break;
        }
        if (datetimeHint.test(text)) {
          container = candidates[i];
          break;
        }
      }
      if (!container) {
        container = candidates[0] || null;
      }
      if (!container) return false;

      container.textContent = this._formatCountdown(this._resolved.boostFinishEntityId);
      container.style.fontVariantNumeric = "tabular-nums";
      return true;
    }

    _startBubbleCountdownTicker() {
      if (this._bubbleCountdownTimer) {
        clearInterval(this._bubbleCountdownTimer);
      }
      this._bubbleCountdownTimer = setInterval(() => {
        this._updateBubbleCountdownText();
      }, 1000);
    }

    _scheduleBubbleInlineMount() {
      if (this._bubbleHookTimer) {
        clearInterval(this._bubbleHookTimer);
        this._bubbleHookTimer = null;
      }
      let attempts = 0;
      this._bubbleHookTimer = setInterval(() => {
        attempts += 1;
        const mounted = this._mountBubbleInlineCountdown();
        if (mounted || attempts >= 80) {
          clearInterval(this._bubbleHookTimer);
          this._bubbleHookTimer = null;
        }
      }, 250);
      this._startBubbleCountdownTicker();
    }
  }

  class ThermostatBoostCountdownCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._timer = null;

      const style = document.createElement("style");
      style.textContent = `
        ha-card {
          padding: 0 8px;
        }
        .row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 10px 4px;
        }
        .label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 500;
        }
        .value {
          color: var(--secondary-text-color);
          font-variant-numeric: tabular-nums;
        }
      `;

      this._card = document.createElement("ha-card");
      this._row = document.createElement("div");
      this._row.classList.add("row");

      this._label = document.createElement("div");
      this._label.classList.add("label");

      this._icon = document.createElement("ha-icon");
      this._name = document.createElement("span");

      this._label.append(this._icon, this._name);

      this._value = document.createElement("div");
      this._value.classList.add("value");

      this._row.append(this._label, this._value);
      this._card.append(this._row);
      this.shadowRoot.append(style, this._card);
    }

    setConfig(config) {
      this._config = { ...(config || {}) };
      this._icon.icon = this._config.icon || "mdi:timer";
      this._name.textContent = this._config.name || "Boost Left";
      this._update();
    }

    set hass(hass) {
      this._hass = hass;
      this._update();
    }

    connectedCallback() {
      this._update();
      if (!this._timer) {
        this._timer = setInterval(() => this._update(), 1000);
      }
    }

    disconnectedCallback() {
      if (this._timer) {
        clearInterval(this._timer);
        this._timer = null;
      }
    }

    _update() {
      if (!this._config?.entity) {
        this._value.textContent = "-";
        return;
      }
      const hass =
        this._hass || document.querySelector("home-assistant")?.hass || null;
      if (!hass) {
        this._value.textContent = "-";
        return;
      }
      this._hass = hass;
      const stateObj = hass.states[this._config.entity];
      let finishIso = stateObj?.state;
      if (!finishIso || finishIso === "unknown" || finishIso === "unavailable") {
        finishIso = stateObj?.attributes?.end_time || null;
      }
      const finish = finishIso ? parseTimestamp(finishIso) : NaN;
      if (Number.isNaN(finish)) {
        this._value.textContent = "-";
        return;
      }
      const now = Date.now();
      let remainingSec = Math.max(0, Math.floor((finish - now) / 1000));
      const hours = Math.floor(remainingSec / 3600);
      remainingSec -= hours * 3600;
      const minutes = Math.floor(remainingSec / 60);
      const seconds = remainingSec - minutes * 60;
      const hh = String(hours).padStart(2, "0");
      const mm = String(minutes).padStart(2, "0");
      const ss = String(seconds).padStart(2, "0");
      this._value.textContent = `${hh}:${mm}:${ss}`;
    }
  }

  class ThermostatBoostCardEditor extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;

      const style = document.createElement("style");
      style.textContent = `
        .editor {
          display: flex;
          flex-direction: column;
          gap: 12px;
          padding: 4px 0;
        }
      `;

      this._container = document.createElement("div");
      this._container.classList.add("editor");

      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (event) => {
        const value = event.detail?.value;
        if (!value) return;
        const deviceId = value.device_id || value;
        this._valueChanged(deviceId);
      });

      this._container.appendChild(this._form);
      this.shadowRoot.append(style, this._container);
    }

    setConfig(config) {
      this._config = { type: `custom:${CARD_TYPE}`, ...(config || {}) };
      this._renderForm();
    }

    set hass(hass) {
      this._hass = hass;
      this._renderForm();
    }

    _renderForm() {
      if (!this._form || !this._hass) return;
      this._form.hass = this._hass;
      this._form.schema = [
        {
          name: "device_id",
          selector: { device: { integration: DOMAIN } },
        },
      ];
      this._form.data = {
        device_id: this._config?.device_id || "",
      };
    }

    _valueChanged(value) {
      if (!value) return;
      if (!this._config) this._config = { type: `custom:${CARD_TYPE}` };
      if (value === this._config.device_id) return;
      const next = { ...this._config, device_id: value };
      delete next.entity_id;
      this._config = next;
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
    }
  }

  customElements.define(CARD_TYPE, ThermostatBoostCard);
  customElements.define(
    "thermostat-boost-countdown",
    ThermostatBoostCountdownCard
  );
  customElements.define("thermostat-boost-card-editor", ThermostatBoostCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TYPE,
    name: "Thermostat Boost",
    description: "Thermostat card with boost controls",
  });

  window.__thermostatBoostCardVersion = VERSION;
  if (window?.console?.info) {
    console.info(`Thermostat Boost Card v${VERSION} loaded`);
  }
})();
