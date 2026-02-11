"""Switch platform for Thermostat Boost."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, UNIQUE_ID_BOOST_ACTIVE
from .entity_base import ThermostatBoostEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for Thermostat Boost."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BoostActiveSwitch(hass, entry, data)])


class BoostActiveSwitch(ThermostatBoostEntity, SwitchEntity, RestoreEntity):
    """Switch indicating whether a boost session is active."""

    _attr_icon = "mdi:fire"

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
