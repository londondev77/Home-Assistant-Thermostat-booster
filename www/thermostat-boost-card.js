/* Thermostat Boost Lovelace Card */
(() => {
  const VERSION = "1.0.0";
  const DOMAIN = "thermostat_boost";
  const CARD_TYPE = "thermostat-boost-card";
  const ALL_CARD_TYPE = "thermostat-boost-all-card";
  const CANCEL_ALL_CARD_TYPE = "thermostat-boost-cancel-all-card";
  const BOOST_TEMP_SUFFIX = "_boost_temperature";
  const BOOST_TIME_SUFFIX = "_boost_time_selector";
  const BOOST_ACTIVE_SUFFIX = "_boost_active";
  const BOOST_FINISH_SUFFIX = "_boost_finish";
  const CALL_FOR_HEAT_ENABLED_SUFFIX = "_call_for_heat_enabled";
  const SCHEDULE_OVERRIDE_SUFFIX = "_disable_schedules";
  const CALL_FOR_HEAT_AGGREGATE_ID = "call_for_heat_aggregate";
  const SCHEDULE_SWITCH_LOCK_TOOLTIP =
    "Turning schedules on/off is disabled when either a boost is active or Disable Schedules is on";
  const SCHEDULE_OVERRIDE_LOCK_TOOLTIP =
    "Disable Schedules cannot be changed when a boost is active";
  const DISABLED_TOGGLE_OPACITY = "0.2";
  const DISABLED_BUTTON_OPACITY = "0.45";
  const MAIN_BOOST_DISABLED_TOOLTIP =
    "Button disabled until a boost duration is selected";
  const ALL_BOOST_DISABLED_TOOLTIP =
    "Button disabled until a thermostat is selected and a boost temperature/time are set";
  const ALL_BOOST_CANCEL_DISABLED_TOOLTIP =
    "Button disabled until a thermostat boost is active";
  const DEVICE_PICKER_STORAGE_KEY =
    "thermostat_boost_device_picker_selection";

  const computeLabel = (device) =>
    device?.name_by_user || device?.name || device?.id || "Thermostat Boost";

  const findEntityId = (entities, deviceId, suffix, preferredDomain = null) => {
    const matches = entities.filter(
      (entry) => entry.device_id === deviceId && entry.entity_id.endsWith(suffix)
    );
    if (matches.length === 0) return null;
    if (preferredDomain) {
      const preferred = matches.find((entry) =>
        entry.entity_id.startsWith(`${preferredDomain}.`)
      );
      if (preferred) return preferred.entity_id;
    }
    const match = matches[0];
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
      this._mainStartButtonRefreshTimer = null;
      this._mainStartButtonRefreshTimers = [];
      this._schedulerLockRefreshTimer = null;
      this._pendingScheduleOverrideLockUntil = 0;
      this._lastBoostActiveState = null;
      this._popupHash = null;

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
      this._lastBoostActiveState = null;
      this._popupHash = null;
      this._root.innerHTML = "";
      this._root.appendChild(this._message);
      this._setMessage("Choose a thermostat to display in this card.");
      this._ensureResolved();
    }

    set hass(hass) {
      this._hass = hass;
      const boostActiveEntityId = this._resolved?.boostActiveEntityId;
      const nextBoostActiveState = boostActiveEntityId
        ? this._hass?.states?.[boostActiveEntityId]?.state ?? null
        : null;
      const boostActiveChanged =
        Boolean(boostActiveEntityId) &&
        nextBoostActiveState !== this._lastBoostActiveState;
      this._lastBoostActiveState = nextBoostActiveState;

      if (boostActiveChanged && this._resolved) {
        if (!this._isPopupOpen()) {
          this._renderCards(this._resolved);
          return;
        }
      }
      if (this._bubbleHeaderCard) this._bubbleHeaderCard.hass = hass;
      if (this._mainStack) this._mainStack.hass = hass;
      this._applySchedulerLockState();
      this._queueMainStartButtonStateRefresh();
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
      if (this._mainStartButtonRefreshTimer) {
        clearTimeout(this._mainStartButtonRefreshTimer);
        this._mainStartButtonRefreshTimer = null;
      }
      this._clearMainStartButtonRefreshTimers();
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
      this._lastBoostActiveState = this._hass?.states?.[
        resolved.boostActiveEntityId
      ]?.state ?? null;
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
          BOOST_ACTIVE_SUFFIX,
          "binary_sensor"
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
      this._popupHash = navAnchor;
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
            const selector =
              '${countdownSubButtonClass} .bubble-sub-button-name-container';
            let container = card.querySelector(selector);
            if (!container) return '';

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
              const currentHass =
                document.querySelector('home-assistant')?.hass ||
                card.hass ||
                hass;
              if (!currentHass) return;
              if (!container || !container.isConnected) {
                container = card.querySelector(selector);
              }
              if (!container) return;
              const activeEntity = currentHass.states['${resolved.boostActiveEntityId}'];
              const isActive = activeEntity?.state === 'on';
              if (!isActive) {
                container.innerText = 'Inactive';
                return;
              }
              const finishEntity = currentHass.states['${resolved.boostFinishEntityId}'];
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
            background-color: \${hass.states['${resolved.thermostatEntityId}']?.attributes?.hvac_action === 'heating'
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
                hold_action: {
                  action: "none",
                },
                double_tap_action: {
                  action: "none",
                },
              },
            ],
          },
        });
      }

      if (useSchedulerComponentCard && resolved.scheduleOverrideEntityId) {
        cards.push({
          type: "tile",
          entity: resolved.scheduleOverrideEntityId,
          name: "Disable Schedules",
          icon: "mdi:grid-off",
          hide_state: true,
          features_position: "inline",
          tap_action: {
            action: "none",
          },
          icon_tap_action: {
            action: "none",
          },
          features: [
            {
              type: "toggle",
            },
          ],
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

    _isPopupOpen() {
      if (!this._popupHash) return false;
      try {
        return window?.location?.hash === this._popupHash;
      } catch (_err) {
        return false;
      }
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
      if (this._hass) stackCard.hass = this._hass;
      this._root.append(stackCard);
      this._mainStack = stackCard;
      this._scheduleSchedulerLockRefresh();
      this._queueMainStartButtonStateRefresh();
    }

    _queueMainStartButtonStateRefresh() {
      if (this._mainStartButtonRefreshTimer) {
        clearTimeout(this._mainStartButtonRefreshTimer);
      }
      this._clearMainStartButtonRefreshTimers();
      this._mainStartButtonRefreshTimer = setTimeout(() => {
        this._mainStartButtonRefreshTimer = null;
        this._applyMainStartButtonDisabledState();
      }, 0);
      [100, 300, 800].forEach((delay) => {
        const timer = setTimeout(() => {
          this._mainStartButtonRefreshTimers = this._mainStartButtonRefreshTimers.filter(
            (entry) => entry !== timer
          );
          this._applyMainStartButtonDisabledState();
        }, delay);
        this._mainStartButtonRefreshTimers.push(timer);
      });
    }


    _applyMainStartButtonDisabledState() {
      const resolved = this._resolved;
      if (!resolved?.boostTimeEntityId || !this._hass) return;
      const stateObj = this._hass.states[resolved.boostTimeEntityId];
      const raw = stateObj?.state;
      const value = raw === undefined || raw === null ? NaN : Number(raw);
      const disabled = !Number.isFinite(value) || value <= 0;
      const action = disabled
        ? { action: "none" }
        : {
            action: "call-service",
            service: `${DOMAIN}.start_boost`,
            service_data: {
              device_id: resolved.deviceId,
            },
          };
      const tiles = this._queryDeepAllFrom(this._root, "hui-tile-card");
      for (const tile of tiles) {
        const tileName = tile?._config?.name || tile?.config?.name || "";
        if (tileName !== "Start Boost") continue;
        this._setTileAction(tile, action);
        this._setTileDisabledVisual(tile, disabled, MAIN_BOOST_DISABLED_TOOLTIP);
      }
    }

    _setTileDisabledVisual(tile, disabled, tooltip) {
      const tileVisual = this._findTileVisualTarget(tile);
      const card = tile.shadowRoot?.querySelector?.("ha-card");
      const targets = [tile, tileVisual, card].filter(Boolean);
      for (const target of targets) {
        if (!target?.style) continue;
        target.style.opacity = disabled ? DISABLED_BUTTON_OPACITY : "";
        target.style.cursor = disabled ? "not-allowed" : "";
      }
      for (const target of targets) {
        if (!target?.setAttribute || !target?.removeAttribute) continue;
        if (disabled) {
          target.setAttribute("title", tooltip);
        } else {
          target.removeAttribute("title");
        }
      }
    }

    _setTileAction(tile, startAction) {
      const current = tile?._config || tile?.config;
      if (!current) return;
      const currentAction = current.tap_action?.action;
      if (currentAction === startAction.action) return;
      const nextConfig = {
        ...current,
        tap_action: startAction,
        icon_tap_action: startAction,
      };
      if (typeof tile.setConfig === "function") {
        tile.setConfig(nextConfig);
        return;
      }
      tile._config = nextConfig;
      tile.config = nextConfig;
      if (typeof tile.requestUpdate === "function") {
        tile.requestUpdate();
      }
    }

    _clearMainStartButtonRefreshTimers() {
      for (const timer of this._mainStartButtonRefreshTimers) {
        clearTimeout(timer);
      }
      this._mainStartButtonRefreshTimers = [];
    }

    _findTileVisualTarget(tile) {
      if (!tile?.shadowRoot?.querySelector) return tile;
      return (
        tile.shadowRoot.querySelector("ha-card") ||
        tile.shadowRoot.querySelector(".container") ||
        tile.shadowRoot.querySelector("#container") ||
        tile.shadowRoot.querySelector(".content") ||
        tile
      );
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
        if (node?.entity === entityId) return true;
        if (node?.config?.entity === entityId) return true;
        if (node?._config?.entity === entityId) return true;
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

    _toggleMatchesEntity(toggleNode, entityId) {
      if (!toggleNode || !entityId) return false;
      let current = toggleNode;
      while (current) {
        if (this._pathContainsEntity([current], entityId)) {
          return true;
        }
        if (current.host && this._pathContainsEntity([current.host], entityId)) {
          return true;
        }
        current = current.parentNode || current.host || null;
      }
      return false;
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
      const onScheduleOverrideToggle =
        this._pathContainsEntity(path, scheduleOverrideEntityId) ||
        this._toggleMatchesEntity(toggleNode, scheduleOverrideEntityId);
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
      ) || this._toggleMatchesEntity(
        toggleNode,
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
      this._applySchedulerLockState();
      if (this._schedulerLockRefreshTimer) {
        clearTimeout(this._schedulerLockRefreshTimer);
      }
      // Re-apply a few times because scheduler-card internals can mount asynchronously.
      this._schedulerLockRefreshTimer = setTimeout(() => {
        this._applySchedulerLockState();
      }, 100);
      setTimeout(() => {
        this._applySchedulerLockState();
      }, 300);
      setTimeout(() => {
        this._applySchedulerLockState();
      }, 800);
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
        if (
          !this._pathContainsEntity(parentPath, overrideEntityId) &&
          !this._toggleMatchesEntity(toggle, overrideEntityId)
        ) {
          return;
        }
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
      const opacity = locked ? DISABLED_TOGGLE_OPACITY : "";
      const switchVisual = this._findSwitchVisualTarget(toggle) || toggle;
      if (switchVisual?.style) {
        switchVisual.style.opacity = opacity;
      }
      const innerSwitch = switchVisual?.shadowRoot?.querySelector?.(".switch");
      if (innerSwitch?.style) {
        innerSwitch.style.opacity = opacity;
      }
    }

    _findSwitchVisualTarget(toggle) {
      if (!toggle) return null;
      let switchFallback = null;
      let current = toggle;
      while (current) {
        const tag = current?.tagName?.toLowerCase?.();
        if (tag === "ha-control-switch") {
          return current;
        }
        if (current.classList?.contains("mdc-switch")) {
          return current;
        }
        if (!switchFallback && current.classList?.contains("switch")) {
          switchFallback = current;
        }
        current = current.parentNode || current.host || null;
      }

      const selector = "ha-control-switch, .mdc-switch, .switch";
      if (toggle.shadowRoot?.querySelector) {
        const inShadow = toggle.shadowRoot.querySelector(selector);
        if (inShadow) return inShadow;
      }

      if (typeof toggle.querySelector === "function") {
        const child = toggle.querySelector(selector);
        if (child) return child;
      }

      return switchFallback;
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

  class ThermostatBoostAllCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
      this._config = null;
      this._helpers = null;
      this._stackConfig = null;
      this._stackCard = null;
      this._devices = [];
      this._loading = false;
      this._needsDeviceRefresh = true;
      this._error = "";
      this._tempDelta = 0;
      this._hours = 0;
      this._startButtonRefreshTimer = null;
      this._startButtonRefreshTimers = [];
      this._selectedDeviceIds = [];
      this._selectionListenerBound = false;

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
      this._root.append(this._message);
      this.shadowRoot.append(style, this._root);
    }

    static getStubConfig() {
      return {
        type: `custom:${ALL_CARD_TYPE}`,
      };
    }

    getCardSize() {
      return 4;
    }

    setConfig(config) {
      this._config = { ...(config || {}) };
      this._needsDeviceRefresh = true;
      this._renderMessage("Loading Thermostat Boost devices...");
      this._ensureResolved();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._stackCard) this._stackCard.hass = this._createProxyHass();
      this._queueStartButtonStateRefresh();
      this._ensureResolved();
    }

    disconnectedCallback() {
      if (this._startButtonRefreshTimer) {
        clearTimeout(this._startButtonRefreshTimer);
        this._startButtonRefreshTimer = null;
      }
      this._clearStartButtonRefreshTimers();
    }

    _renderMessage(text) {
      this._message.textContent = text;
      if (!this._root.contains(this._message)) {
        this._root.innerHTML = "";
        this._root.append(this._message);
      }
    }

    async _getCardHelpers() {
      if (this._helpers) return this._helpers;
      if (!window.loadCardHelpers) return null;
      this._helpers = await window.loadCardHelpers();
      return this._helpers;
    }

    _isVirtualEntity(entityId) {
      return (
        entityId === "number.thermostat_boost_all_temperature_offset" ||
        entityId === "number.thermostat_boost_all_time_selector"
      );
    }

    _toStateString(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "0";
      return Number.isInteger(num) ? String(num) : String(num);
    }

    _temperatureDeltaConfig() {
      const rawUnit = this._hass?.config?.unit_system?.temperature || "";
      const normalized = String(rawUnit).toUpperCase();
      const isFahrenheit = normalized.includes("F");
      return {
        unit: isFahrenheit ? "\u00B0F" : "\u00B0C",
        min: isFahrenheit ? -10 : -5,
        max: isFahrenheit ? 10 : 5,
      };
    }

    async _ensureResolved() {
      if (!this._hass || this._loading) return;
      if (!this._needsDeviceRefresh && this._devices.length > 0 && this._stackCard) {
        return;
      }
      this._loading = true;
      try {
        const [devices, entities] = await Promise.all([
          this._hass.callWS({ type: "config/device_registry/list" }),
          this._hass.callWS({ type: "config/entity_registry/list" }),
        ]);
        this._devices = devices
          .filter((device) => {
            const domainIdentifiers = (device.identifiers || []).filter(
              (identifier) => identifier[0] === DOMAIN
            );
            if (domainIdentifiers.length === 0) return false;
            return !domainIdentifiers.some(
              (identifier) => identifier[1] === CALL_FOR_HEAT_AGGREGATE_ID
            );
          })
          .map((device) => {
            const deviceId = device.id;
            const thermostatEntityId = findThermostatEntityId(device);
            return {
              deviceId,
              label: computeLabel(device),
              thermostatEntityId,
              boostActiveEntityId: findEntityId(
                entities,
                deviceId,
                BOOST_ACTIVE_SUFFIX,
                "binary_sensor"
              ),
              boostFinishEntityId: findEntityId(
                entities,
                deviceId,
                BOOST_FINISH_SUFFIX
              ),
            };
          })
          .filter(
            (device) =>
              Boolean(device.deviceId) &&
              Boolean(device.thermostatEntityId) &&
              Boolean(device.boostActiveEntityId) &&
              Boolean(device.boostFinishEntityId)
          );
        this._error = "";
        this._needsDeviceRefresh = false;
      } catch (_err) {
        this._error = "Unable to resolve Thermostat Boost devices.";
        this._needsDeviceRefresh = true;
      } finally {
        this._loading = false;
        this._renderStack();
      }
    }

    _getActiveDevices() {
      if (!this._hass) return [];
      return this._devices.filter(
        (device) => this._hass.states[device.boostActiveEntityId]?.state === "on"
      );
    }

    _getCountdownText() {
      if (!this._hass) return null;
      const activeDevices = this._getActiveDevices();
      if (activeDevices.length === 0) return null;

      const endTimestamps = activeDevices
        .map((device) => {
          const finishState = this._hass.states[device.boostFinishEntityId];
          const raw =
            finishState?.state || finishState?.attributes?.end_time || null;
          return parseTimestamp(raw);
        })
        .filter((value) => !Number.isNaN(value));
      if (endTimestamps.length === 0) return null;
      const maxEnd = Math.max(...endTimestamps);
      return new Date(maxEnd).toISOString();
    }


    _hoursToDuration(hoursValue) {
      const totalMinutes = Math.max(0, Math.round(Number(hoursValue) * 60));
      return {
        hours: Math.floor(totalMinutes / 60),
        minutes: totalMinutes % 60,
      };
    }

    async _handleStart() {
      if (!this._hass) return;
      this._syncSelectedDeviceIdsFromPicker();
      const duration = this._hoursToDuration(this._hours);
      const totalMinutes = duration.hours * 60 + duration.minutes;
      if (totalMinutes <= 0 || this._tempDelta === 0) return;

      if (!this._selectedDeviceIds || this._selectedDeviceIds.length === 0) {
        this._error = "No thermostats selected for boost.";
        this._renderStack();
        return;
      }

      const deviceIds = this._devices
        .map((device) => device.deviceId)
        .filter(Boolean);
      if (deviceIds.length === 0) {
        this._error = "No eligible thermostats found for multiple thermostat boost.";
        this._renderStack();
        return;
      }

      this._error = "";
      try {
        await this._hass.callService(DOMAIN, "start_boost", {
          device_id: this._selectedDeviceIds,
          time: duration,
          temperature_delta: this._tempDelta,
        });
        // Reset sliders after a successful start.
        this._tempDelta = 0;
        this._hours = 0;
        if (this._stackCard) {
          this._stackCard.hass = this._createProxyHass();
          this._queueStartButtonStateRefresh();
        } else {
          await this._renderStack();
        }
      } catch (_err) {
        this._error = "Failed to start boost for selected thermostats.";
        this._renderStack();
      }
    }

    async _handleCancel() {
      if (!this._hass) return;
      const activeDeviceIds = this._getActiveDevices().map(
        (device) => device.deviceId
      );
      if (activeDeviceIds.length === 0) return;

      this._error = "";
      try {
        await this._hass.callService(DOMAIN, "finish_boost", {
          device_id: activeDeviceIds,
        });
      } catch (_err) {
        this._error = "Failed to cancel active boosts.";
        this._renderStack();
      }
    }

    _virtualStates() {
      const tempConfig = this._temperatureDeltaConfig();
      const finishIso = this._getCountdownText();
      return {
        "number.thermostat_boost_all_temperature_offset": {
          entity_id: "number.thermostat_boost_all_temperature_offset",
          state: this._toStateString(this._tempDelta),
          attributes: {
            friendly_name: "All Thermostats Temperature Offset",
            min: tempConfig.min,
            max: tempConfig.max,
            step: 0.5,
            unit_of_measurement: tempConfig.unit,
          },
        },
        "number.thermostat_boost_all_time_selector": {
          entity_id: "number.thermostat_boost_all_time_selector",
          state: this._toStateString(this._hours),
          attributes: {
            friendly_name: "All Thermostats Boost Duration",
            min: 0,
            max: 24,
            step: 0.5,
            unit_of_measurement: "hrs",
          },
        },
        "sensor.thermostat_boost_all_finish": {
          entity_id: "sensor.thermostat_boost_all_finish",
          state: finishIso || "Inactive",
          attributes: {
            friendly_name: "All Thermostats Boost Finish",
            end_time: finishIso || null,
          },
        },
      };
    }

    _createProxyHass() {
      if (!this._hass) return null;
      const states = {
        ...this._hass.states,
        ...this._virtualStates(),
      };
      return {
        ...this._hass,
        states,
        callService: async (domain, service, serviceData, target) => {
          if (domain === "number" && service === "set_value") {
            const entityId = serviceData?.entity_id;
            if (this._isVirtualEntity(entityId)) {
              const raw = Number(serviceData?.value);
              if (!Number.isFinite(raw)) return;
              const tempConfig = this._temperatureDeltaConfig();
              if (entityId === "number.thermostat_boost_all_temperature_offset") {
                this._tempDelta = Math.max(tempConfig.min, Math.min(tempConfig.max, raw));
              } else if (entityId === "number.thermostat_boost_all_time_selector") {
                this._hours = Math.max(0, Math.min(24, raw));
              }
              if (this._stackCard) {
                this._stackCard.hass = this._createProxyHass();
                this._queueStartButtonStateRefresh();
              } else {
                await this._renderStack();
              }
              return;
            }
          }

          if (
            domain === DOMAIN &&
            service === "start_boost" &&
            serviceData?.device_id === "__all_thermostat_boost_devices__"
          ) {
            await this._handleStart();
            return;
          }
          if (
            domain === DOMAIN &&
            service === "finish_boost" &&
            serviceData?.device_id === "__all_thermostat_boost_devices__"
          ) {
            await this._handleCancel();
            return;
          }
          return this._hass.callService(domain, service, serviceData, target);
        },
      };
    }

    _buildStackConfig() {
      const disabled =
        this._hours <= 0 ||
        this._tempDelta === 0 ||
        !this._selectedDeviceIds ||
        this._selectedDeviceIds.length === 0;
      const startAction = disabled
        ? { action: "none" }
        : {
            action: "call-service",
            service: `${DOMAIN}.start_boost`,
            service_data: {
              device_id: "__all_thermostat_boost_devices__",
            },
          };
      const devicePickerCard = {
        type: "custom:thermostat-boost-device-picker",
        devices: this._devices.map((device) => {
          const icon =
            this._hass?.states?.[device.thermostatEntityId]?.attributes?.icon ||
            "mdi:thermostat";
          return {
            device_id: device.deviceId,
            label: device.label,
            icon,
          };
        }),
      };
      const cards = [
        devicePickerCard,
        {
          type: "vertical-stack",
          cards: [
            {
              type: "custom:slider-entity-row",
              entity: "number.thermostat_boost_all_temperature_offset",
              name: "Boost Temperature Offset",
              full_row: true,
              show_icon: true,
              step: 0.5,
              toggle: false,
              hide_state: false,
              icon: "mdi:thermometer",
            },
            {
              type: "custom:slider-entity-row",
              entity: "number.thermostat_boost_all_time_selector",
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
        {
          type: "horizontal-stack",
          cards: [
            {
              type: "tile",
              color: "green",
              name: "Start boost on selected thermostats",
              hide_state: true,
              vertical: false,
              icon: "mdi:rocket-launch",
              entity: "sensor.thermostat_boost_all_finish",
              tap_action: startAction,
              icon_tap_action: startAction,
              hold_action: {
                action: "none",
              },
              double_tap_action: {
                action: "none",
              },
            },
          ],
        },
      ];

      if (this._error) {
        cards.push({
          type: "markdown",
          content: `**Error:** ${this._error}`,
        });
      }
      return {
        type: "vertical-stack",
        cards,
      };
    }

    async _renderStack() {
      if (!this._hass) {
        this._renderMessage("Waiting for Home Assistant...");
        return;
      }
      if (this._loading) {
        this._renderMessage("Loading Thermostat Boost devices...");
        return;
      }
      if (this._error && this._devices.length === 0) {
        this._renderMessage(this._error);
        return;
      }
      if (this._devices.length === 0) {
        this._renderMessage("No Thermostat Boost devices found.");
        return;
      }

      this._stackConfig = this._buildStackConfig();
      const helpers = await this._getCardHelpers();
      if (!helpers) {
        this._renderMessage("Unable to load card helpers.");
        return;
      }

      const nextCard = await helpers.createCardElement(this._stackConfig);
      const proxiedHass = this._createProxyHass();
      if (proxiedHass) nextCard.hass = proxiedHass;

      this._root.innerHTML = "";
      this._root.append(nextCard);
      this._stackCard = nextCard;
      this._bindPickerEvents();
      this._queueStartButtonStateRefresh();
    }

    _queueStartButtonStateRefresh() {
      if (this._startButtonRefreshTimer) {
        clearTimeout(this._startButtonRefreshTimer);
      }
      this._clearStartButtonRefreshTimers();
      this._startButtonRefreshTimer = setTimeout(() => {
        this._startButtonRefreshTimer = null;
        this._applyStartButtonDisabledState();
      }, 0);
      [200].forEach((delay) => {
        const timer = setTimeout(() => {
          this._startButtonRefreshTimers = this._startButtonRefreshTimers.filter(
            (entry) => entry !== timer
          );
          this._applyStartButtonDisabledState();
        }, delay);
        this._startButtonRefreshTimers.push(timer);
      });
    }


    _setTileDisabledVisual(tile, disabled, tooltip) {
      const tileVisual = this._findTileVisualTarget(tile);
      const card = tile.shadowRoot?.querySelector?.("ha-card");
      const targets = [tile, tileVisual, card].filter(Boolean);
      for (const target of targets) {
        if (!target?.style) continue;
        target.style.opacity = disabled ? DISABLED_BUTTON_OPACITY : "";
        target.style.cursor = disabled ? "not-allowed" : "";
      }
      for (const target of targets) {
        if (!target?.setAttribute || !target?.removeAttribute) continue;
        if (disabled) {
          target.setAttribute("title", tooltip);
        } else {
          target.removeAttribute("title");
        }
      }
    }

    _applyStartButtonDisabledState() {
      const disabled =
        this._hours <= 0 ||
        this._tempDelta === 0 ||
        !this._selectedDeviceIds ||
        this._selectedDeviceIds.length === 0;
      const cancelDisabled = this._getActiveDevices().length === 0;
      const startAction = disabled
        ? { action: "none" }
        : {
            action: "call-service",
            service: `${DOMAIN}.start_boost`,
            service_data: {
              device_id: "__all_thermostat_boost_devices__",
            },
          };
      const cancelAction = cancelDisabled
        ? { action: "none" }
        : {
            action: "call-service",
            service: `${DOMAIN}.finish_boost`,
            service_data: {
              device_id: "__all_thermostat_boost_devices__",
            },
          };
      const tiles = this._queryDeepAllFrom(this._root, "hui-tile-card");
      for (const tile of tiles) {
        const tileName = tile?._config?.name || tile?.config?.name || "";
        if (tileName === "Start boost on selected thermostats") {
          this._setTileAction(tile, startAction);
          this._setTileDisabledVisual(tile, disabled, ALL_BOOST_DISABLED_TOOLTIP);
          continue;
        }
        if (tileName === "Cancel boost on ALL thermostats") {
          this._setTileAction(tile, cancelAction);
          this._setTileDisabledVisual(
            tile,
            cancelDisabled,
            ALL_BOOST_CANCEL_DISABLED_TOOLTIP
          );
        }
      }
    }
    _setTileAction(tile, startAction) {
      const current = tile?._config || tile?.config;
      if (!current) return;
      const currentAction = current.tap_action?.action;
      if (currentAction === startAction.action) return;
      const nextConfig = {
        ...current,
        tap_action: startAction,
        icon_tap_action: startAction,
      };
      if (typeof tile.setConfig === "function") {
        tile.setConfig(nextConfig);
        return;
      }
      tile._config = nextConfig;
      tile.config = nextConfig;
      if (typeof tile.requestUpdate === "function") {
        tile.requestUpdate();
      }
    }

    _clearStartButtonRefreshTimers() {
      for (const timer of this._startButtonRefreshTimers) {
        clearTimeout(timer);
      }
      this._startButtonRefreshTimers = [];
    }

    _findTileVisualTarget(tile) {
      if (!tile?.shadowRoot?.querySelector) return tile;
      return (
        tile.shadowRoot.querySelector("ha-card") ||
        tile.shadowRoot.querySelector(".container") ||
        tile.shadowRoot.querySelector("#container") ||
        tile.shadowRoot.querySelector(".content") ||
        tile
      );
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

    _bindPickerEvents() {
      if (!this._root || this._selectionListenerBound) return;
      this._selectionListenerBound = true;
      this._root.addEventListener("thermostat-boost-selection-changed", (event) => {
        const selection = event?.detail?.selection;
        if (!selection || typeof selection !== "object") return;
        const allowed = new Set(
          this._devices.map((device) => device.deviceId).filter(Boolean)
        );
        this._selectedDeviceIds = Object.keys(selection).filter(
          (deviceId) => selection[deviceId] && allowed.has(deviceId)
        );
        this._queueStartButtonStateRefresh();
      });
      const picker = this._queryDeepAllFrom(
        this._root,
        "thermostat-boost-device-picker"
      )[0];
      if (picker && typeof picker.getSelection === "function") {
        this._syncSelectedDeviceIdsFromPicker();
        this._queueStartButtonStateRefresh();
      }
    }

    _syncSelectedDeviceIdsFromPicker() {
      if (!this._root) return;
      const picker = this._queryDeepAllFrom(
        this._root,
        "thermostat-boost-device-picker"
      )[0];
      if (!picker || typeof picker.getSelection !== "function") return;
      const selection = picker.getSelection();
      if (!selection || typeof selection !== "object") return;
      const allowed = new Set(
        this._devices.map((device) => device.deviceId).filter(Boolean)
      );
      this._selectedDeviceIds = Object.keys(selection).filter(
        (deviceId) => selection[deviceId] && allowed.has(deviceId)
      );
    }
  }

  class ThermostatBoostCancelAllCard extends ThermostatBoostAllCard {
    static getStubConfig() {
      return {
        type: `custom:${CANCEL_ALL_CARD_TYPE}`,
      };
    }

    getCardSize() {
      return 1;
    }

    _buildStackConfig() {
      const cancelDisabled = this._getActiveDevices().length === 0;
      const cancelAction = cancelDisabled
        ? { action: "none" }
        : {
            action: "call-service",
            service: `${DOMAIN}.finish_boost`,
            service_data: {
              device_id: "__all_thermostat_boost_devices__",
            },
          };
      const cards = [
        {
          type: "horizontal-stack",
          cards: [
            {
              type: "tile",
              entity: "sensor.thermostat_boost_all_finish",
              tap_action: cancelAction,
              icon_tap_action: cancelAction,
              color: "red",
              name: "Cancel boost on ALL thermostats",
              hide_state: true,
              icon: "mdi:rocket",
            },
          ],
        },
      ];

      if (this._error) {
        cards.push({
          type: "markdown",
          content: `**Error:** ${this._error}`,
        });
      }

      return {
        type: "vertical-stack",
        cards,
      };
    }
  }

  class ThermostatBoostDividerCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = `
        .divider {
          border: 0;
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
          opacity: 1;
          margin: 6px 0;
        }
      `;
      const hr = document.createElement("hr");
      hr.classList.add("divider");
      this.shadowRoot.append(style, hr);
    }

    setConfig(_config) {}
    set hass(_hass) {}
    getCardSize() {
      return 1;
    }
  }

  class ThermostatBoostDevicePickerCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._devices = [];
      this._selection = {};
      this._selectionLoaded = false;
      this._selectionLoadPromise = null;
    }

    setConfig(config) {
      this._config = config || {};
      this._devices = Array.isArray(this._config.devices)
        ? this._config.devices
        : [];
      for (const device of this._devices) {
        const deviceId = device?.device_id;
        if (!deviceId) continue;
        if (this._selection[deviceId] === undefined) {
          this._selection[deviceId] = true;
        }
      }
      this._ensureSelectionLoaded();
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._ensureSelectionLoaded();
      this._render();
    }

    getCardSize() {
      return Math.max(1, this._devices.length);
    }

    getSelection() {
      return { ...this._selection };
    }

    async _ensureSelectionLoaded() {
      if (this._selectionLoaded || this._selectionLoadPromise) return;
      this._selectionLoadPromise = (async () => {
        const hass =
          this._hass || document.querySelector("home-assistant")?.hass || null;
        let stored = null;
        if (hass?.callWS) {
          try {
            const result = await hass.callWS({
              type: "storage/get",
              key: DEVICE_PICKER_STORAGE_KEY,
            });
            stored = result?.value ?? result?.data ?? result ?? null;
          } catch (_err) {
            stored = null;
          }
        }
        if (!stored) {
          try {
            const raw = window?.localStorage?.getItem?.(
              DEVICE_PICKER_STORAGE_KEY
            );
            stored = raw ? JSON.parse(raw) : null;
          } catch (_err) {
            stored = null;
          }
        }
        if (stored && typeof stored === "object" && !Array.isArray(stored)) {
          for (const device of this._devices) {
            const deviceId = device?.device_id;
            if (!deviceId) continue;
            if (Object.prototype.hasOwnProperty.call(stored, deviceId)) {
              this._selection[deviceId] = Boolean(stored[deviceId]);
            }
          }
        }
        this._selectionLoaded = true;
        this._selectionLoadPromise = null;
        this._emitSelectionChanged();
        this._render();
      })();
    }

    async _persistSelection() {
      try {
        window?.localStorage?.setItem?.(
          DEVICE_PICKER_STORAGE_KEY,
          JSON.stringify(this._selection)
        );
      } catch (_err) {
        // Ignore local storage failures
      }
      const hass =
        this._hass || document.querySelector("home-assistant")?.hass || null;
      if (!hass?.callWS) return;
      try {
        await hass.callWS({
          type: "storage/save",
          key: DEVICE_PICKER_STORAGE_KEY,
          value: this._selection,
        });
        return;
      } catch (_err) {
        // Fall back to alternate storage payload
      }
      try {
        await hass.callWS({
          type: "storage/save",
          key: DEVICE_PICKER_STORAGE_KEY,
          data: this._selection,
        });
      } catch (_err) {
        // Ignore storage failures
      }
    }

    _render() {
      if (!this.shadowRoot) return;
      this.shadowRoot.innerHTML = "";

      const allSelected =
        this._devices.length > 0 &&
        this._devices.every((device) =>
          Boolean(this._selection[device?.device_id])
        );

      const style = document.createElement("style");
      style.textContent = `
        .card {
          padding: 8px 12px;
        }
        .row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 6px 2px;
        }
        .row-header {
          padding-bottom: 10px;
          border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
          margin-bottom: 6px;
        }
        .row-footer {
          padding-top: 10px;
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
          margin-top: 6px;
        }
        .label {
          display: flex;
          align-items: center;
          gap: 8px;
          min-width: 0;
          color: var(--primary-text-color);
          font-size: 14px;
        }
        .label span {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        ha-icon {
          color: var(--secondary-text-color);
        }
      `;

      const card = document.createElement("ha-card");
      card.classList.add("card");

      const content = document.createElement("div");

      const headerRow = document.createElement("div");
      headerRow.classList.add("row", "row-header");

      const headerLabel = document.createElement("div");
      headerLabel.classList.add("label");

      const headerIcon = document.createElement("ha-icon");
      headerIcon.setAttribute("icon", "mdi:select-all");

      const headerText = document.createElement("span");
      headerText.textContent = "Select all";

      headerLabel.append(headerIcon, headerText);

      const headerToggle = document.createElement("ha-switch");
      headerToggle.checked = allSelected;
      headerToggle.addEventListener("change", (event) => {
        const checked = Boolean(event?.target?.checked);
        for (const device of this._devices) {
          const deviceId = device?.device_id;
          if (!deviceId) continue;
          this._selection[deviceId] = checked;
        }
        this._emitSelectionChanged();
        this._persistSelection();
        this._render();
      });

      headerRow.append(headerLabel, headerToggle);
      content.append(headerRow);

      for (const device of this._devices) {
        const row = document.createElement("div");
        row.classList.add("row");

        const label = document.createElement("div");
        label.classList.add("label");

        const icon = document.createElement("ha-icon");
        icon.setAttribute("icon", device?.icon || "mdi:thermostat");

        const name = document.createElement("span");
        name.textContent = device?.label || "Thermostat";

        label.append(icon, name);

        const toggle = document.createElement("ha-switch");
        const deviceId = device?.device_id || "";
        toggle.checked = Boolean(this._selection[deviceId]);
        toggle.addEventListener("change", (event) => {
          this._selection[deviceId] = Boolean(event?.target?.checked);
          this._emitSelectionChanged();
          this._persistSelection();
          this._render();
        });

        row.append(label, toggle);
        content.append(row);
      }

      const footerRow = document.createElement("div");
      footerRow.classList.add("row", "row-footer");

      const footerLabel = document.createElement("div");
      footerLabel.classList.add("label");

      const footerIcon = document.createElement("ha-icon");
      footerIcon.setAttribute("icon", "mdi:swap-vertical");

      const footerText = document.createElement("span");
      footerText.textContent = "Invert selection";

      footerLabel.append(footerIcon, footerText);

      const footerToggle = document.createElement("ha-switch");
      footerToggle.checked = false;
      footerToggle.addEventListener("change", () => {
        for (const device of this._devices) {
          const deviceId = device?.device_id;
          if (!deviceId) continue;
          this._selection[deviceId] = !this._selection[deviceId];
        }
        this._emitSelectionChanged();
        this._persistSelection();
        this._render();
      });

      footerRow.append(footerLabel, footerToggle);
      content.append(footerRow);

      card.append(content);
      this.shadowRoot.append(style, card);
    }

    _emitSelectionChanged() {
      this.dispatchEvent(
        new CustomEvent("thermostat-boost-selection-changed", {
          detail: { selection: { ...this._selection } },
          bubbles: true,
          composed: true,
        })
      );
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
  if (!customElements.get("thermostat-boost-divider")) {
    customElements.define(
      "thermostat-boost-divider",
      ThermostatBoostDividerCard
    );
  }
  if (!customElements.get("thermostat-boost-device-picker")) {
    customElements.define(
      "thermostat-boost-device-picker",
      ThermostatBoostDevicePickerCard
    );
  }
  if (!customElements.get("thermostat-boost-card-editor")) {
    customElements.define("thermostat-boost-card-editor", ThermostatBoostCardEditor);
  }
  if (!customElements.get(ALL_CARD_TYPE)) {
    customElements.define(ALL_CARD_TYPE, ThermostatBoostAllCard);
  }
  if (!customElements.get(CANCEL_ALL_CARD_TYPE)) {
    customElements.define(CANCEL_ALL_CARD_TYPE, ThermostatBoostCancelAllCard);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Thermostat Boost",
      description: "Thermostat overview card and boost controls overlay",
    });
  }
  if (!window.customCards.some((card) => card.type === ALL_CARD_TYPE)) {
    window.customCards.push({
      type: ALL_CARD_TYPE,
      name: "Thermostat Boost - multiple thermostats",
      description: "Apply an offset boost to a number of Thermostat Boost devices",
    });
  }
  if (!window.customCards.some((card) => card.type === CANCEL_ALL_CARD_TYPE)) {
    window.customCards.push({
      type: CANCEL_ALL_CARD_TYPE,
      name: "Thermostat Boost - cancel all button",
      description: "A button to cancel all active boosts for Thermostat Boost devices. This is kept separate from the other cards so you can place it where it makes sense to you",
    });
  }

  window.__thermostatBoostCardVersion = VERSION;
  if (window?.console?.info) {
    console.info(`Thermostat Boost Card v${VERSION} loaded`);
  }
})();
