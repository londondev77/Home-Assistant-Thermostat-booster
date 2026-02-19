"""Number platform for Thermostat Boost."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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

        return raw
    return None


def _dynamic_boost_temperature_bounds(
    hass: HomeAssistant, entity_id: str
) -> tuple[float, float]:
    """Derive slider bounds from thermostat attributes with normalized fallbacks."""
    state = hass.states.get(entity_id)
    attributes = state.attributes if state is not None else {}
    is_us_customary = (
        hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
    )
    default_min_temp = 40.0 if is_us_customary else 5.0
    default_max_temp = 80.0 if is_us_customary else 25.0

    def _read_bound(key: str) -> float | None:
        value = attributes.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    min_temp = _read_bound("min_temp")
    max_temp = _read_bound("max_temp")

    # Missing/invalid values normalize to 0 first.
    if min_temp is None:
        min_temp = 0.0
    if max_temp is None:
        max_temp = 0.0

    # Some thermostats report both bounds as 0 when limits are not meaningful.
    if min_temp == 0.0 and max_temp == 0.0:
        min_temp = default_min_temp
        max_temp = default_max_temp

    # If max is unavailable (normalized to 0) but min is meaningful, keep min and
    # use a safe default max.
    if max_temp == 0.0 and min_temp > 0.0:
        max_temp = default_max_temp

    # Guard against invalid inverted bounds from integrations.
    if min_temp > max_temp:
        min_temp = default_min_temp
        max_temp = default_max_temp

    return min_temp, max_temp


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
    _attr_native_min_value = 0.0
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
        self._thermostat_entity_id = thermostat_entity_id
        min_temp, max_temp = _dynamic_boost_temperature_bounds(
            hass, thermostat_entity_id
        )
        self._attr_native_min_value = min_temp
        self._attr_native_max_value = max_temp

        self._native_value: float | None = _default_boost_temperature(
            hass, thermostat_entity_id
        )

        temp_unit = (
            "F"
            if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
            else "C"
        )
        self._attr_native_unit_of_measurement = temp_unit
        self._attr_unit_of_measurement = temp_unit

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            try:
                self._native_value = float(state.state)
            except (TypeError, ValueError):
                pass
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._thermostat_entity_id],
                self._async_handle_thermostat_state_change,
            )
        )
        self._async_refresh_dynamic_bounds()

    @callback
    def _async_handle_thermostat_state_change(self, _event) -> None:
        """Refresh slider bounds when thermostat attributes change."""
        self._async_refresh_dynamic_bounds()

    @callback
    def _async_refresh_dynamic_bounds(self) -> None:
        """Recompute and apply min/max bounds from thermostat state."""
        min_temp, max_temp = _dynamic_boost_temperature_bounds(
            self.hass, self._thermostat_entity_id
        )
        if (
            self._attr_native_min_value == min_temp
            and self._attr_native_max_value == max_temp
        ):
            return

        self._attr_native_min_value = min_temp
        self._attr_native_max_value = max_temp

        if self._native_value is not None:
            if self._native_value < min_temp:
                self._native_value = min_temp
            elif self._native_value > max_temp:
                self._native_value = max_temp

        self.async_write_ha_state()

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
