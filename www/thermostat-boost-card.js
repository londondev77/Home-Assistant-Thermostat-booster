/* Thermostat Boost Lovelace Card */
(() => {
  const VERSION = "1.0.0";
  const DOMAIN = "thermostat_boost";
  const CARD_TYPE = "thermostat-boost-card";
  const BOOST_TEMP_SUFFIX = "_boost_temperature";
  const BOOST_TIME_SUFFIX = "_boost_time_selector";
  const BOOST_ACTIVE_SUFFIX = "_boost_active";
  const BOOST_FINISH_SUFFIX = "_boost_finish";
  const CALL_FOR_HEAT_ENABLED_SUFFIX = "_call_for_heat_enabled";
  const SCHEDULE_OVERRIDE_SUFFIX = "_disable_schedules";
  const SCHEDULE_SWITCH_LOCK_TOOLTIP =
    "Turning schedules on/off is disabled when either a boost is active or Disable Schedules is on";
  const SCHEDULE_OVERRIDE_LOCK_TOOLTIP =
    "Disable Schedules cannot be changed when a boost is active";
  const DISABLED_TOGGLE_OPACITY = "20%";
  const SLIDER_STATE_MIN_WIDTH = "8ch";

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
      this._schedulerLockRefreshTimer = null;
      this._pendingScheduleOverrideLockUntil = 0;

      const style = document.createElement("style");
      style.textContent = `
        .stack {
          display: flex;
          flex-direction: column;
          gap: 2px;
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
      this._root.addEventListener(
        "click",
        (ev) => this._handleSchedulerLockEvent(ev),
        true
      );
      this._root.addEventListener(
        "pointerdown",
        (ev) => this._handleSchedulerLockEvent(ev),
        true
      );
      this._root.addEventListener(
        "keydown",
        (ev) => this._handleSchedulerLockEvent(ev),
        true
      );
      this._root.addEventListener(
        "mousemove",
        (ev) => this._handleSchedulerLockHover(ev),
        true
      );
    }

    static getConfigElement() {
      return document.createElement("thermostat-boost-card-editor");
    }

    static getStubConfig() {
      return {
        type: `custom:${CARD_TYPE}`,
        use_scheduler_component_card: true,
      };
    }

    setConfig(config) {
      this._config = {
        type: `custom:${CARD_TYPE}`,
        use_scheduler_component_card: true,
        ...(config || {}),
      };
      window.__thermostatBoostCardLastConfig = this._config;
      this._resolved = null;
      this._resolving = null;
      this._root.innerHTML = "";
      this._root.appendChild(this._message);
      this._setMessage("Choose a thermostat to display in this card.");
      this._ensureResolved();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._bubbleHeaderCard) this._bubbleHeaderCard.hass = hass;
      if (this._mainStack) this._mainStack.hass = hass;
      this._applySchedulerLockState();
      this._applySliderStateStyles();
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
      if (this._schedulerLockRefreshTimer) {
        clearTimeout(this._schedulerLockRefreshTimer);
        this._schedulerLockRefreshTimer = null;
      }
      if (this._bubbleHeaderCard?.timer) {
        clearInterval(this._bubbleHeaderCard.timer);
        this._bubbleHeaderCard.timer = null;
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
        deviceId: deviceId,
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
        callForHeatEnabledEntityId: findEntityId(
          entityList,
          deviceId,
          CALL_FOR_HEAT_ENABLED_SUFFIX
        ),
        scheduleOverrideEntityId: findEntityId(
          entityList,
          deviceId,
          SCHEDULE_OVERRIDE_SUFFIX
        ),
      };
    }

    _renderCards(resolved) {
      if (this._bubbleHeaderCard?.timer) {
        clearInterval(this._bubbleHeaderCard.timer);
        this._bubbleHeaderCard.timer = null;
      }
      const cards = [];

      const navSlug = (resolved.label || "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
      const navAnchor = navSlug ? `#${navSlug}_detail` : "#detail";
      const useSchedulerComponentCard =
        this._config?.use_scheduler_component_card !== false;
      const showInlinePopupPreview = this._isInCardEditorPreview();
      const hasScheduleOverrideButton =
        useSchedulerComponentCard && Boolean(resolved.scheduleOverrideEntityId);
      const countdownSubButtonClass = hasScheduleOverrideButton
        ? ".bubble-sub-button-2"
        : ".bubble-sub-button-1";
      const heatingSubButtonClass = hasScheduleOverrideButton
        ? ".bubble-sub-button-4"
        : ".bubble-sub-button-3";
      const headerSubButtons = [];
      if (hasScheduleOverrideButton) {
        headerSubButtons.push({
          entity: resolved.scheduleOverrideEntityId,
          icon: "mdi:grid-off",
          show_background: true,
          state_background: false,
          tap_action: {
            action: "navigate",
            navigation_path: navAnchor,
          },
          visibility: [
            {
              condition: "state",
              entity: resolved.scheduleOverrideEntityId,
              state: "on",
            },
          ],
          fill_width: false,
        });
      }
      headerSubButtons.push(
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
        }
      );

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
        //icon: "mdi:home-thermometer",
        sub_button: {
          main: headerSubButtons,
          bottom: [],
        },
        styles: `
          \${(() => {
            const container = card.querySelector(
              '${countdownSubButtonClass} .bubble-sub-button-name-container'
            );
            if (!container) return '';

            const finishEntity = hass.states['${resolved.boostFinishEntityId}'];
            const activeEntity = hass.states['${resolved.boostActiveEntityId}'];
            const isActive = activeEntity?.state === 'on';

            const normalizeDate = (value) => {
              if (!value || typeof value !== 'string') return null;
              let text = value.trim();
              if (text.includes(' ') && !text.includes('T')) {
                text = text.replace(' ', 'T');
              }
              text = text.replace(/(\\.\\d{3})\\d+/, '$1');
              const parsed = new Date(text);
              if (!Number.isNaN(parsed.valueOf())) return parsed;
              const fallback = new Date(value);
              return Number.isNaN(fallback.valueOf()) ? null : fallback;
            };

            const update = () => {
              if (!isActive) {
                container.innerText = 'Inactive';
                return;
              }
              const endIso =
                finishEntity?.state ||
                finishEntity?.attributes?.end_time ||
                null;
              const endTime = normalizeDate(endIso);
              if (!endTime) {
                container.innerText = 'Inactive';
                return;
              }
              const now = new Date();
              let remainingSec = Math.max(0, Math.floor((endTime - now) / 1000));
              const hours = Math.floor(remainingSec / 3600);
              remainingSec -= hours * 3600;
              const minutes = Math.floor(remainingSec / 60);
              const seconds = remainingSec - minutes * 60;
              const hh = String(hours).padStart(2, '0');
              const mm = String(minutes).padStart(2, '0');
              const ss = String(seconds).padStart(2, '0');
              container.innerText = \`\${hh}:\${mm}:\${ss}\`;
            };

            if (!isActive) {
              if (card.timer) {
                clearInterval(card.timer);
                card.timer = null;
              }
              container.innerText = 'Inactive';
              return '';
            }

            if (!card.timer) {
              card.timer = setInterval(update, 1000);
            }
            update();
            return '';
          })()}
          ${countdownSubButtonClass} .bubble-name {
            font-size: 11px;
            line-height: 1.1;
          }
          ${heatingSubButtonClass} {
            background-color: \${hass.states['${resolved.thermostatEntityId}'].attributes.hvac_action === 'heating'
              ? 'var(--state-climate-heat-color)'
              : 'var(--card-background-color)'} !important;
          }
        `,
        slider_fill_orientation: "left",
        slider_value_position: "right",
      };

      if (!showInlinePopupPreview) {
        cards.push({
          type: "custom:bubble-card",
          card_type: "pop-up",
          hash: navAnchor,
          name: resolved.label || "Thermostat",
          icon: "mdi:home-thermometer",
          show_header: true,
          button_type: "name",
          sub_button: {
            main: [],
            bottom: [],
          },
          styles: `
            \${(() => {
              const thermostatState = hass.states['${resolved.thermostatEntityId}'];
              const thermostatIcon = thermostatState?.attributes?.icon || 'mdi:home-thermometer';
              const headerIcon =
                card.querySelector('.bubble-header .bubble-icon ha-icon') ||
                card.querySelector('.bubble-header .bubble-icon');
              if (!headerIcon) return '';
              if ('icon' in headerIcon) {
                headerIcon.icon = thermostatIcon;
              } else {
                headerIcon.setAttribute('icon', thermostatIcon);
              }
              return '';
            })()}
          `,
          slider_fill_orientation: "left",
          slider_value_position: "right",
        });
      } else {
        cards.push({
          type: "heading",
          icon: "mdi:card-text-outline",
          heading_style: "title",
          heading: "Popup preview",
        });
      }

      cards.push({
        type: "thermostat",
        entity: resolved.thermostatEntityId,
        show_current_as_primary: true,
        features: [
          {
            type: "climate-hvac-modes",
            style: "icons",
          },
          {
            type: "climate-preset-modes",
            style: "dropdown",
          },
        ],
      });

      cards.push({
        type: "heading",
        icon: "mdi:rocket-launch",
        heading_style: "title",
        heading: "Boost",
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
                name: "Boost Temperature",
                full_row: true,
                show_icon: true,
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
                name: "Boost Duration",
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
                    device_id: resolved.deviceId,
                  },
                },
                icon_tap_action: {
                  action: "call-service",
                  service: `${DOMAIN}.finish_boost`,
                  service_data: {
                    device_id: resolved.deviceId,
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
                name: "Boost Time",
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
              above: 0,
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
                    device_id: resolved.deviceId,
                  },
                },
                icon_tap_action: {
                  action: "call-service",
                  service: `${DOMAIN}.start_boost`,
                  service_data: {
                    device_id: resolved.deviceId,
                  },
                },
              },
            ],
          },
        });
      }

      if (useSchedulerComponentCard && resolved.scheduleOverrideEntityId) {
        const entities = [];
        entities.push({
          entity: resolved.scheduleOverrideEntityId,
          name: "Disable Schedules",
          icon: "mdi:grid-off",
          tap_action: {
            action: "none",
          },
          hold_action: {
            action: "none",
          },
        });

        cards.push({
          type: "entities",
          show_header_toggle: false,
          entities,
        });
      }

      if (useSchedulerComponentCard && resolved.thermostatEntityId) {
        cards.push({
          type: "custom:scheduler-card",
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
          default_editor: "scheme",
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
      this._scheduleSchedulerLockRefresh();
    }

    _isScheduleOverrideOn() {
      const entityId = this._resolved?.scheduleOverrideEntityId;
      if (!entityId || !this._hass) return false;
      const stateOn = this._hass.states?.[entityId]?.state === "on";
      if (stateOn) {
        this._pendingScheduleOverrideLockUntil = 0;
        return true;
      }
      return Date.now() < this._pendingScheduleOverrideLockUntil;
    }

    _isBoostActive() {
      const entityId = this._resolved?.boostActiveEntityId;
      if (!entityId || !this._hass) return false;
      return this._hass.states?.[entityId]?.state === "on";
    }

    _isInCardEditorPreview() {
      const editorTags = new Set([
        "hui-dialog-create-card",
        "hui-dialog-edit-card",
        "hui-dialog-edit-dashboard-card",
        "hui-dialog-create",
        "hui-card-picker",
        "hui-card-preview",
        "hui-card-element-editor",
      ]);
      let node = this;
      while (node) {
        const tag = node?.tagName?.toLowerCase?.();
        if (tag && editorTags.has(tag)) {
          return true;
        }
        node = node.parentNode || node.host || null;
      }
      return false;
    }

    _useSchedulerComponentCard() {
      return this._config?.use_scheduler_component_card !== false;
    }

    _isSchedulerSwitchLockActive() {
      if (!this._useSchedulerComponentCard()) return false;
      return this._isBoostActive() || this._isScheduleOverrideOn();
    }

    _pathContainsEntity(path, entityId) {
      if (!entityId) return false;
      return path.some((node) => {
        const tag = node?.tagName?.toLowerCase?.();
        if (tag === "hui-toggle-entity-row") {
          return (
            node?.config?.entity === entityId ||
            node?.entityId === entityId
          );
        }
        if (node?.config?.entity === entityId) return true;
        if (node?.entityId === entityId) return true;
        if (typeof node?.getAttribute === "function") {
          return (
            node.getAttribute("entity") === entityId ||
            node.getAttribute("data-entity") === entityId ||
            node.getAttribute("data-entity-id") === entityId
          );
        }
        return false;
      });
    }

    _handleSchedulerLockEvent(ev) {
      if (!this._useSchedulerComponentCard()) return;
      this._noteScheduleOverrideIntent(ev);
      this._handleSchedulerLockClick(ev);
    }

    _noteScheduleOverrideIntent(ev) {
      if (!this._useSchedulerComponentCard()) return;
      const entityId = this._resolved?.scheduleOverrideEntityId;
      if (!entityId || !this._hass) return;
      if (this._hass.states?.[entityId]?.state === "on") {
        this._pendingScheduleOverrideLockUntil = 0;
        return;
      }

      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      const clickedOverrideRow = this._pathContainsEntity(path, entityId);
      if (!clickedOverrideRow) return;

      this._pendingScheduleOverrideLockUntil = Date.now() + 1500;
      this._applySchedulerLockState();
    }

    _handleSchedulerLockClick(ev) {
      if (!this._useSchedulerComponentCard()) return;
      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      const toggleSelector =
        "ha-switch, mwc-switch, .switch, [role='switch'], input[type='checkbox']";
      const toggleNode = path.find((node) => node?.matches?.(toggleSelector));
      const onToggle = Boolean(toggleNode);
      if (!onToggle) return;

      const scheduleOverrideEntityId = this._resolved?.scheduleOverrideEntityId;
      const onScheduleOverrideToggle = this._pathContainsEntity(
        path,
        scheduleOverrideEntityId
      );
      if (onScheduleOverrideToggle) {
        if (!this._isBoostActive()) return;
        if (toggleNode?.style) {
          toggleNode.style.cursor = "not-allowed";
        }
        toggleNode?.setAttribute?.("title", SCHEDULE_OVERRIDE_LOCK_TOOLTIP);
      } else {
        if (!this._isSchedulerSwitchLockActive()) return;
        const inSchedulerCard = path.some(
          (node) => node?.tagName?.toLowerCase?.() === "scheduler-card"
        );
        if (!inSchedulerCard) return;
        if (toggleNode?.style) {
          toggleNode.style.cursor = "not-allowed";
        }
        toggleNode?.setAttribute?.("title", SCHEDULE_SWITCH_LOCK_TOOLTIP);
      }

      if (ev.type === "keydown") {
        const key = ev.key || "";
        if (key === "Tab" || key === "Escape") return;
      }

      this._clearSchedulerCardFocus(path);

      ev.preventDefault();
      ev.stopPropagation();
      if (typeof ev.stopImmediatePropagation === "function") {
        ev.stopImmediatePropagation();
      }
    }

    _clearSchedulerCardFocus(path = null) {
      const active =
        this.shadowRoot?.activeElement ||
        document.activeElement ||
        null;
      if (active && typeof active.blur === "function") {
        active.blur();
      }

      const nodes = Array.isArray(path) ? path : [];
      for (const node of nodes) {
        if (typeof node?.blur === "function") {
          node.blur();
        }
      }
    }

    _handleSchedulerLockHover(ev) {
      if (!this._useSchedulerComponentCard()) {
        this.style.cursor = "";
        return;
      }
      const toggleSelector =
        "ha-switch, mwc-switch, .switch, [role='switch'], input[type='checkbox']";
      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      const toggleNode = path.find((node) => node?.matches?.(toggleSelector));
      if (!toggleNode) {
        this.style.cursor = "";
        return;
      }

      const onScheduleOverrideToggle = this._pathContainsEntity(
        path,
        this._resolved?.scheduleOverrideEntityId
      );
      if (onScheduleOverrideToggle) {
        const lockOverride = this._isBoostActive();
        if (toggleNode?.style) {
          toggleNode.style.cursor = lockOverride ? "not-allowed" : "";
        }
        if (lockOverride) {
          toggleNode.setAttribute("title", SCHEDULE_OVERRIDE_LOCK_TOOLTIP);
        } else {
          toggleNode.removeAttribute("title");
        }
        this.style.cursor = lockOverride ? "not-allowed" : "";
        return;
      }

      if (!this._isSchedulerSwitchLockActive()) {
        this.style.cursor = "";
        return;
      }
      const inSchedulerCard = path.some(
        (node) => node?.tagName?.toLowerCase?.() === "scheduler-card"
      );
      if (!inSchedulerCard) {
        this.style.cursor = "";
        return;
      }

      if (toggleNode?.style) {
        toggleNode.style.cursor = "not-allowed";
      }
      toggleNode?.setAttribute?.("title", SCHEDULE_SWITCH_LOCK_TOOLTIP);
      this.style.cursor = toggleNode ? "not-allowed" : "";
    }

    _scheduleSchedulerLockRefresh() {
      if (!this._useSchedulerComponentCard()) {
        this.style.cursor = "";
        if (this._schedulerLockRefreshTimer) {
          clearTimeout(this._schedulerLockRefreshTimer);
          this._schedulerLockRefreshTimer = null;
        }
        this._applySliderStateStyles();
        return;
      }
      this._applySchedulerLockState();
      this._applySliderStateStyles();
      if (this._schedulerLockRefreshTimer) {
        clearTimeout(this._schedulerLockRefreshTimer);
      }
      // Re-apply a few times because scheduler-card internals can mount asynchronously.
      this._schedulerLockRefreshTimer = setTimeout(() => {
        this._applySchedulerLockState();
        this._applySliderStateStyles();
      }, 100);
      setTimeout(() => {
        this._applySchedulerLockState();
        this._applySliderStateStyles();
      }, 300);
      setTimeout(() => {
        this._applySchedulerLockState();
        this._applySliderStateStyles();
      }, 800);
    }

    _applySliderStateStyles() {
      const targetEntities = [
        this._resolved?.boostTemperatureEntityId,
        this._resolved?.boostTimeEntityId,
      ].filter(Boolean);
      if (targetEntities.length === 0) return;

      const candidates = this._queryDeepAll(".state, .value");
      for (const node of candidates) {
        if (!node?.style) continue;
        const path = [];
        let current = node;
        while (current) {
          path.push(current);
          current = current.parentNode || current.host || null;
        }
        const inTargetSlider = targetEntities.some((entityId) =>
          this._pathContainsEntity(path, entityId)
        );
        if (!inTargetSlider) continue;

        node.style.whiteSpace = "nowrap";
        node.style.minWidth = SLIDER_STATE_MIN_WIDTH;
        node.style.textAlign = "right";
        node.style.display = "inline-block";
      }
    }

    _applySchedulerLockState() {
      if (!this._useSchedulerComponentCard()) {
        this.style.cursor = "";
        return;
      }
      const schedulerCards = this._queryDeepAll("scheduler-card");
      const lock = this._isSchedulerSwitchLockActive();
      for (const schedulerCard of schedulerCards) {
        const toggles = this._queryDeepAllFrom(
          schedulerCard,
          "ha-switch, mwc-switch, .switch, [role='switch'], input[type='checkbox']"
        );
        schedulerCard.style.pointerEvents = "";
        toggles.forEach((toggle) => {
          toggle.style.pointerEvents = "";
          toggle.style.cursor = lock ? "not-allowed" : "";
          this._setMdcSwitchOpacity(toggle, lock);
          if (lock) {
            toggle.setAttribute("title", SCHEDULE_SWITCH_LOCK_TOOLTIP);
          } else {
            toggle.removeAttribute("title");
          }
          if (lock && typeof toggle.blur === "function") toggle.blur();
        });
      }

      const overrideToggleLock = this._isBoostActive();
      const overrideEntityId = this._resolved?.scheduleOverrideEntityId;
      const allToggles = this._queryDeepAll(
        "ha-switch, mwc-switch, .switch, [role='switch'], input[type='checkbox']"
      );
      allToggles.forEach((toggle) => {
        const parentPath = [];
        let node = toggle;
        while (node) {
          parentPath.push(node);
          node = node.parentNode || node.host || null;
        }
        if (!this._pathContainsEntity(parentPath, overrideEntityId)) return;
        toggle.style.pointerEvents = "";
        toggle.style.cursor = overrideToggleLock ? "not-allowed" : "";
        this._setMdcSwitchOpacity(toggle, overrideToggleLock);
        if (overrideToggleLock) {
          toggle.setAttribute("title", SCHEDULE_OVERRIDE_LOCK_TOOLTIP);
          if (typeof toggle.blur === "function") toggle.blur();
        } else {
          toggle.removeAttribute("title");
        }
      });
    }

    _setMdcSwitchOpacity(toggle, locked) {
      const mdcSwitch = this._findMdcSwitch(toggle);
      if (!mdcSwitch?.style) return;
      mdcSwitch.style.opacity = locked ? DISABLED_TOGGLE_OPACITY : "";
    }

    _findMdcSwitch(toggle) {
      if (!toggle) return null;
      if (toggle.classList?.contains("mdc-switch")) {
        return toggle;
      }

      if (typeof toggle.closest === "function") {
        const closest = toggle.closest(".mdc-switch");
        if (closest) return closest;
      }

      if (toggle.shadowRoot?.querySelector) {
        const inShadow = toggle.shadowRoot.querySelector(".mdc-switch");
        if (inShadow) return inShadow;
      }

      if (typeof toggle.querySelector === "function") {
        return toggle.querySelector(".mdc-switch");
      }

      return null;
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
      const countdownButtonClass = this._resolved?.scheduleOverrideEntityId
        ? ".bubble-sub-button-2"
        : ".bubble-sub-button-1";
      const subButton = this._queryDeep(countdownButtonClass);
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
      if (Number.isNaN(finish)) return "Inactive";

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
      return this._queryDeepAllFrom(this._root, selector);
    }

    _queryDeepAllFrom(root, selector) {
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

      visit(root);
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
        :host {
          display: block;
          height: 100%;
        }
        ha-card {
          padding: 0 8px;
          height: 100%;
          display: flex;
          align-items: center;
        }
        .row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 0 12px;
          width: 100%;
          min-height: var(--tile-height, 56px);
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
      this._name.textContent = this._config.name || "Boost Time";
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
        this._value.textContent = "Inactive";
        return;
      }
      const hass =
        this._hass || document.querySelector("home-assistant")?.hass || null;
      if (!hass) {
        this._value.textContent = "Inactive";
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
        this._value.textContent = "Inactive";
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
      this._schedulerWarningToken = 0;

      const style = document.createElement("style");
      style.textContent = `
        .editor {
          display: flex;
          flex-direction: column;
          gap: 12px;
          padding: 4px 0;
        }
        .editor-help {
          color: var(--secondary-text-color);
          font-size: 13px;
          line-height: 1.35;
        }
        .editor-warning {
          display: none;
          padding: 10px 12px;
          border-radius: 8px;
          border: 1px solid var(--warning-color, #f4b400);
          background: var(--warning-bg-color, rgba(244, 180, 0, 0.12));
          color: var(--primary-text-color);
          font-size: 13px;
          line-height: 1.35;
        }
      `;

      this._container = document.createElement("div");
      this._container.classList.add("editor");

      this._helper = document.createElement("div");
      this._helper.classList.add("editor-help");
      this._helper.textContent =
        "Choose a thermostat to display in this card.";

      this._warning = document.createElement("div");
      this._warning.classList.add("editor-warning");

      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (event) => {
        const value = event.detail?.value;
        if (value === undefined || value === null) return;
        this._valueChanged(value);
      });

      this._container.append(this._helper, this._form, this._warning);
      this.shadowRoot.append(style, this._container);
    }

    setConfig(config) {
      this._config = {
        type: `custom:${CARD_TYPE}`,
        use_scheduler_component_card: true,
        ...(config || {}),
      };
      this._renderForm();
    }

    set hass(hass) {
      this._hass = hass;
      this._renderForm();
    }

    _renderForm() {
      if (!this._form || !this._hass) return;
      this._form.hass = this._hass;
      this._form.computeLabel = (schema) => {
        if (schema?.name === "device_id") return "Thermostat";
        if (schema?.name === "use_scheduler_component_card") {
          return "Include Scheduler card";
        }
        return schema?.label || schema?.name || "";
      };
      this._form.schema = [
        {
          name: "device_id",
          selector: {
            device: {
              integration: DOMAIN,
              entity: { domain: "sensor" },
            },
          },
        },
        {
          name: "use_scheduler_component_card",
          selector: {
            boolean: {},
          },
        },
      ];
      this._form.data = {
        device_id: this._config?.device_id || "",
        use_scheduler_component_card:
          this._config?.use_scheduler_component_card !== false,
      };
      this._updateSchedulerWarning();
    }

    _valueChanged(value) {
      if (value === undefined || value === null) return;
      if (!this._config) {
        this._config = {
          type: `custom:${CARD_TYPE}`,
          use_scheduler_component_card: true,
        };
      }
      const next = { ...this._config };

      if (typeof value === "object" && !Array.isArray(value)) {
        if ("device_id" in value) {
          next.device_id = value.device_id;
        }
        if ("use_scheduler_component_card" in value) {
          next.use_scheduler_component_card = Boolean(
            value.use_scheduler_component_card
          );
        }
      } else if (typeof value === "string") {
        next.device_id = value;
      } else if (typeof value === "boolean") {
        next.use_scheduler_component_card = value;
      } else {
        return;
      }

      if (next.use_scheduler_component_card === undefined) {
        next.use_scheduler_component_card = true;
      }
      delete next.entity_id;
      if (JSON.stringify(next) === JSON.stringify(this._config)) return;
      this._config = next;
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        })
      );
      this._updateSchedulerWarning();
    }

    async _updateSchedulerWarning() {
      if (!this._warning) return;
      const deviceId = this._config?.device_id;
      const useSchedulerComponentCard =
        this._config?.use_scheduler_component_card !== false;
      if (!this._hass || !deviceId || useSchedulerComponentCard) {
        this._warning.style.display = "none";
        this._warning.textContent = "";
        return;
      }

      const token = ++this._schedulerWarningToken;
      try {
        const hasSchedules = await this._deviceHasAssignedSchedules(deviceId);
        if (token !== this._schedulerWarningToken) return;
        if (hasSchedules === true) {
          this._warning.textContent =
            "The thermostat you're adding has schedules assigned to it. It is strongly recommended to include the Scheduler card to avoid confusion.";
          this._warning.style.display = "block";
          return;
        }
        if (hasSchedules === false) {
          this._warning.style.display = "none";
          this._warning.textContent = "";
        }
      } catch (_err) {
        // Keep silent in editor, but clear stale text if detection hard-fails.
        this._warning.style.display = "none";
        this._warning.textContent = "";
      }
    }

    async _deviceHasAssignedSchedules(deviceId) {
      const devices = await this._hass.callWS({
        type: "config/device_registry/list",
      });

      const device = devices.find((entry) => entry.id === deviceId);
      if (!device) return false;
      const thermostatEntityId = findThermostatEntityId(device);
      if (!thermostatEntityId) return false;
      const thermostatName =
        this._hass.states?.[thermostatEntityId]?.attributes?.friendly_name || "";
      const thermostatNameLower =
        typeof thermostatName === "string" ? thermostatName.toLowerCase() : "";

      const matchesAssignedEntities = (assigned) => {
        if (typeof assigned === "string") {
          return assigned === thermostatEntityId;
        }
        if (Array.isArray(assigned)) {
          return assigned.some(
            (entityId) =>
              typeof entityId === "string" && entityId === thermostatEntityId
          );
        }
        return false;
      };

      const matchesTags = (tags) => {
        if (!thermostatNameLower) return false;
        if (typeof tags === "string") {
          return tags.toLowerCase().includes(thermostatNameLower);
        }
        if (Array.isArray(tags)) {
          return tags.some(
            (tag) =>
              typeof tag === "string" &&
              tag.toLowerCase().includes(thermostatNameLower)
          );
        }
        return false;
      };

      let inspectedSchedulerAssignments = false;
      for (const [entityId, state] of Object.entries(this._hass.states || {})) {
        if (!entityId.startsWith("switch.")) continue;
        const attrs = state?.attributes || {};
        const assigned = attrs.entities;
        const hasAssignmentData = assigned !== undefined && assigned !== null;
        const hasTagData = attrs.tags !== undefined && attrs.tags !== null;
        if (!hasAssignmentData && !hasTagData) continue;
        inspectedSchedulerAssignments = true;

        if (matchesAssignedEntities(assigned)) {
          return true;
        }
        if (matchesTags(attrs.tags)) {
          return true;
        }
      }
      // Null indicates scheduler assignment data could not be read reliably.
      return inspectedSchedulerAssignments ? false : null;
    }
  }

  if (!customElements.get(CARD_TYPE)) {
    customElements.define(CARD_TYPE, ThermostatBoostCard);
  }
  if (!customElements.get("thermostat-boost-countdown")) {
    customElements.define(
      "thermostat-boost-countdown",
      ThermostatBoostCountdownCard
    );
  }
  if (!customElements.get("thermostat-boost-card-editor")) {
    customElements.define("thermostat-boost-card-editor", ThermostatBoostCardEditor);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Thermostat Boost",
      description: "Thermostat overview card and boost controls overlay",
    });
  }

  window.__thermostatBoostCardVersion = VERSION;
  if (window?.console?.info) {
    console.info(`Thermostat Boost Card v${VERSION} loaded`);
  }
})();
