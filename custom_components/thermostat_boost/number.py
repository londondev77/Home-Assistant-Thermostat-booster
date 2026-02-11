"""Number platform for Thermostat Boost."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_THERMOSTAT,
    DOMAIN,
    UNIQUE_ID_BOOST_TEMPERATURE,
    UNIQUE_ID_TIME_SELECTOR,
)
from .entity_base import ThermostatBoostEntity


def _default_boost_temperature(hass: HomeAssistant, entity_id: str) -> float | None:
    """Try to derive a default boost temperature from the thermostat."""
    state = hass.states.get(entity_id)
    if state is None:
        return None

    for key in ("temperature", "current_temperature"):
        value = state.attributes.get(key)
        if value is None:
            continue
        try:
            raw = float(value)
        except (TypeError, ValueError):
            return None

        if hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
            return TemperatureConverter.convert(
                raw,
                hass.config.units.temperature_unit,
                UnitOfTemperature.CELSIUS,
            )
        return raw
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for Thermostat Boost."""
    data = hass.data[DOMAIN][entry.entry_id]
    thermostat_entity_id = data[CONF_THERMOSTAT]
    async_add_entities(
        [
            BoostTemperatureNumber(hass, entry, data, thermostat_entity_id),
            BoostTimeSelectorNumber(hass, entry, data),
        ]
    )


class BoostTemperatureNumber(ThermostatBoostEntity, NumberEntity, RestoreEntity):
    """Number for boost temperature."""

    _attr_icon = "mdi:thermometer-plus"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 5.0
    _attr_native_max_value = 25.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "C"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        data: dict,
        thermostat_entity_id: str,
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Boost Temperature",
            unique_id_suffix=UNIQUE_ID_BOOST_TEMPERATURE,
        )
        self._native_value: float | None = _default_boost_temperature(
            hass, thermostat_entity_id
        )

        self._attr_unit_of_measurement = "C"

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            try:
                self._native_value = float(state.state)
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self._native_value = float(value)
        self.async_write_ha_state()


class BoostTimeSelectorNumber(ThermostatBoostEntity, NumberEntity, RestoreEntity):
    """Number for boost duration selection."""

    _attr_icon = "mdi:timer-sand"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 24.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "hrs"
    _attr_unit_of_measurement = "hrs"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Boost Time Selector",
            unique_id_suffix=UNIQUE_ID_TIME_SELECTOR,
        )
        self._native_value: float | None = 0.0

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            try:
                self._native_value = float(state.state)
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self._native_value = float(value)
        self.async_write_ha_state()
