"""Sensor platform for Thermostat Boost."""

from __future__ import annotations

from datetime import timedelta
from typing import Callable

import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.util import dt as dt_util

from .boost_actions import async_create_scheduler_scene, async_finish_boost_for_entry
from .const import (
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    SERVICE_TIMER_CANCEL,
    SERVICE_TIMER_START,
    SERVICE_START_BOOST,
    SERVICE_FINISH_BOOST,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_BOOST_FINISH,
    UNIQUE_ID_BOOST_TEMPERATURE,
    UNIQUE_ID_TIME_SELECTOR,
)
from .entity_base import ThermostatBoostEntity
from .timer_manager import async_get_timer_registry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Thermostat Boost."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BoostFinishSensor(hass, entry, data)])

    platform = entity_platform.async_get_current_platform()
    services_key = "timer_services_registered"
    if not hass.data[DOMAIN].get(services_key):
        platform.async_register_entity_service(
            SERVICE_TIMER_START,
            {vol.Optional("minutes"): vol.Coerce(float)},
            "async_start_timer",
        )
        platform.async_register_entity_service(
            SERVICE_TIMER_CANCEL,
            {},
            "async_cancel_timer",
        )
        platform.async_register_entity_service(
            SERVICE_START_BOOST,
            {},
            "async_start_boost",
        )
        platform.async_register_entity_service(
            SERVICE_FINISH_BOOST,
            {},
            "async_finish_boost",
        )
        hass.data[DOMAIN][services_key] = True


class BoostFinishSensor(ThermostatBoostEntity, SensorEntity, RestoreEntity):
    """Sensor representing the boost finish date/time."""

    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Boost Finish",
            unique_id_suffix=UNIQUE_ID_BOOST_FINISH,
        )
        self._native_value = "Inactive"
        self._attr_extra_state_attributes = {"status": "inactive"}
        self._timer = None
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Restore state on startup and attach timer listeners."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                parsed = dt_util.parse_datetime(state.state)
                if parsed is not None:
                    self._native_value = parsed
                else:
                    self._native_value = state.state

        registry = await async_get_timer_registry(self.hass)
        self._timer = await registry.async_get_timer(
            self._entry.entry_id,
            self._data[CONF_THERMOSTAT],
            self._data[DATA_THERMOSTAT_NAME],
        )
        self._remove_listener = self._timer.add_listener(self._handle_timer_update)
        self._handle_timer_update()

    async def async_will_remove_from_hass(self) -> None:
        """Detach timer listeners."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_timer_update(self) -> None:
        if self._timer is None:
            return
        snapshot = self._timer.snapshot()
        if snapshot.end is None:
            self._native_value = "Inactive"
            status = "inactive"
        else:
            self._native_value = snapshot.end
            status = snapshot.status
        self._attr_extra_state_attributes = {
            "status": status,
            "end_time": snapshot.end.isoformat() if snapshot.end else None,
        }
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the current value."""
        return self._native_value

    async def async_start_timer(self, minutes: float | None = None) -> None:
        """Start the timer using minutes or the time selector value."""
        if self._timer is None:
            return

        if minutes is None:
            minutes = _get_time_selector_value(self.hass, self._entry.entry_id)

        if minutes is None:
            minutes = 0.0

        await self._timer.async_start(timedelta(minutes=float(minutes)))

    async def async_cancel_timer(self) -> None:
        """Cancel the timer."""
        if self._timer is None:
            return
        await self._timer.async_cancel()

    async def async_start_boost(self) -> None:
        """Start boost: set temperature, start timer, mark active."""
        if self._timer is None:
            return

        temperature_c = _get_number_value(
            self.hass, self._entry.entry_id, UNIQUE_ID_BOOST_TEMPERATURE
        )
        duration_minutes = _get_number_value(
            self.hass, self._entry.entry_id, UNIQUE_ID_TIME_SELECTOR
        )

        if temperature_c is None:
            return
        if duration_minutes is None:
            duration_minutes = 0.0

        target_temp = temperature_c
        if self.hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
            target_temp = TemperatureConverter.convert(
                temperature_c,
                UnitOfTemperature.CELSIUS,
                self.hass.config.units.temperature_unit,
            )


        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": self._data[CONF_THERMOSTAT],
                "temperature": target_temp,
            },
            blocking=True,
        )

        await self._timer.async_start(timedelta(minutes=float(duration_minutes)))

        boost_active_entity_id = _get_entity_id(
            self.hass, self._entry.entry_id, UNIQUE_ID_BOOST_ACTIVE
        )
        if boost_active_entity_id:
            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": boost_active_entity_id},
                blocking=True,
            )

        scheduler_switches = await async_create_scheduler_scene(
            self.hass, self._entry.entry_id, self._data[DATA_THERMOSTAT_NAME]
        )
        if scheduler_switches:
            await self.hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": scheduler_switches},
                blocking=True,
            )

    async def async_finish_boost(self) -> None:
        """Finish boost: clear timer, reset temperature, mark inactive."""
        await async_finish_boost_for_entry(self.hass, self._entry.entry_id)


@callback
def _get_time_selector_value(hass: HomeAssistant, entry_id: str) -> float | None:
    return _get_number_value(hass, entry_id, UNIQUE_ID_TIME_SELECTOR)


@callback
def _get_entity_id(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> str | None:
    entity_reg = er.async_get(hass)
    unique_id = f"{entry_id}_{unique_id_suffix}"
    for entry in entity_reg.entities.values():
        if entry.unique_id == unique_id:
            return entry.entity_id
    return None


@callback
def _get_number_value(
    hass: HomeAssistant, entry_id: str, unique_id_suffix: str
) -> float | None:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None
