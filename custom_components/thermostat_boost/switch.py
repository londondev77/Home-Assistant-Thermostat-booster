"""Switch platform for Thermostat Boost."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .boost_actions import (
    async_cancel_pending_scheduler_callbacks,
    async_create_scheduler_scene,
    async_restore_scheduler_snapshot,
)
from .const import (
    CONF_THERMOSTAT,
    DOMAIN,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_CALL_FOR_HEAT_ENABLED,
    UNIQUE_ID_SCHEDULE_OVERRIDE,
)
from .entity_base import ThermostatBoostEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for Thermostat Boost."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BoostActiveSwitch(hass, entry, data),
            ScheduleOverrideSwitch(hass, entry, data),
            CallForHeatEnabledSwitch(hass, entry, data),
        ]
    )


class BoostActiveSwitch(ThermostatBoostEntity, SwitchEntity, RestoreEntity):
    """Switch indicating whether a boost session is active."""

    _attr_icon = "mdi:rocket-launch"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Boost Active",
            unique_id_suffix=UNIQUE_ID_BOOST_ACTIVE,
        )
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        self._is_on = False
        self.async_write_ha_state()


class ScheduleOverrideSwitch(ThermostatBoostEntity, SwitchEntity, RestoreEntity):
    """Switch to suspend thermostat schedules until turned off."""

    _attr_icon = "mdi:grid-off"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Disable Schedules",
            unique_id_suffix=UNIQUE_ID_SCHEDULE_OVERRIDE,
        )
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Snapshot current schedules and suspend them."""
        if self._is_on:
            return
        async_cancel_pending_scheduler_callbacks(self.hass, self._entry.entry_id)

        if not _is_switch_on(self.hass, self._entry.entry_id, UNIQUE_ID_BOOST_ACTIVE):
            scheduler_switches = await async_create_scheduler_scene(
                self.hass,
                self._entry.entry_id,
                self._data[CONF_THERMOSTAT],
            )
            if scheduler_switches:
                await self.hass.services.async_call(
                    "switch",
                    "turn_off",
                    {"entity_id": scheduler_switches},
                    blocking=True,
                )

        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore captured schedules unless a boost is still active."""
        if not self._is_on:
            return

        async_cancel_pending_scheduler_callbacks(self.hass, self._entry.entry_id)
        self._is_on = False
        self.async_write_ha_state()

        if not _is_switch_on(self.hass, self._entry.entry_id, UNIQUE_ID_BOOST_ACTIVE):
            await async_restore_scheduler_snapshot(self.hass, self._entry.entry_id)


class CallForHeatEnabledSwitch(ThermostatBoostEntity, SwitchEntity, RestoreEntity):
    """Switch controlling inclusion in aggregate call-for-heat signal."""

    _attr_icon = "mdi:broadcast"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Call for Heat enabled",
            unique_id_suffix=UNIQUE_ID_CALL_FOR_HEAT_ENABLED,
        )
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        self._is_on = False
        self.async_write_ha_state()


@callback
def _get_entity_id(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> str | None:
    entity_reg = er.async_get(hass)
    unique_id = f"{entry_id}_{unique_id_suffix}"
    for entry in entity_reg.entities.values():
        if entry.unique_id == unique_id:
            return entry.entity_id
    return None


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
