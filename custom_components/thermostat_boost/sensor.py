"""Sensor platform for Thermostat Boost."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Callable

import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.util import dt as dt_util

from .boost_actions import (
    async_create_scheduler_scene,
    async_finish_boost_for_entry,
    async_store_target_temperature_snapshot,
)
from .const import (
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    SERVICE_START_BOOST,
    SERVICE_FINISH_BOOST,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_BOOST_FINISH,
    UNIQUE_ID_BOOST_TEMPERATURE,
    UNIQUE_ID_SCHEDULE_OVERRIDE,
    UNIQUE_ID_TIME_SELECTOR,
)
from .entity_base import ThermostatBoostEntity
from .scheduler_utils import get_scheduler_switches_for_thermostat
from .timer_manager import async_get_timer_registry

_LOGGER = logging.getLogger(__name__)

_START_BOOST_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): vol.Any(str, [str]),
        vol.Optional("entity_id"): vol.Any(str, [str]),
        vol.Optional("time"): vol.Any(
            None,
            str,
            {
                vol.Optional("days", default=0): vol.Coerce(int),
                vol.Optional("hours", default=0): vol.Coerce(int),
                vol.Optional("minutes", default=0): vol.Coerce(int),
                vol.Optional("seconds", default=0): vol.Coerce(int),
                vol.Optional("milliseconds", default=0): vol.Coerce(int),
            },
        ),
        vol.Optional("temperature_c"): vol.Coerce(float),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Thermostat Boost."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BoostFinishSensor(hass, entry, data)])

    platform = entity_platform.async_get_current_platform()
    services_key = "finish_boost_service_registered"
    if not hass.data[DOMAIN].get(services_key):
        platform.async_register_entity_service(
            SERVICE_FINISH_BOOST,
            {},
            "async_finish_boost",
        )
        hass.data[DOMAIN][services_key] = True

    start_boost_service_key = "start_boost_service_registered"
    if not hass.data[DOMAIN].get(start_boost_service_key):
        async def _async_handle_start_boost(call: ServiceCall) -> None:
            entry_ids: set[str] = set()
            for device_id in _normalize_to_list(call.data.get("device_id")):
                entry_id = _entry_id_from_device_id(hass, device_id)
                if entry_id is None:
                    raise HomeAssistantError(
                        f"Unable to resolve thermostat_boost entry from device_id: {device_id}"
                    )
                entry_ids.add(entry_id)

            for entity_id in _normalize_to_list(call.data.get("entity_id")):
                entry_id = _entry_id_from_entity_id(hass, entity_id)
                if entry_id is None:
                    raise HomeAssistantError(
                        f"Unable to resolve thermostat_boost entry from entity_id: {entity_id}"
                    )
                entry_ids.add(entry_id)

            if not entry_ids:
                raise HomeAssistantError("start_boost requires device_id.")

            for entry_id in entry_ids:
                await async_start_boost_for_entry(
                    hass,
                    entry_id,
                    time=call.data.get("time"),
                    temperature_c=call.data.get("temperature_c"),
                )

        hass.services.async_register(
            DOMAIN,
            SERVICE_START_BOOST,
            _async_handle_start_boost,
            schema=_START_BOOST_SERVICE_SCHEMA,
        )
        hass.data[DOMAIN][start_boost_service_key] = True


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
        restored_end: datetime | None = None
        if (state := await self.async_get_last_state()) is not None:
            if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                parsed = dt_util.parse_datetime(state.state)
                if parsed is not None:
                    self._native_value = parsed
                    restored_end = dt_util.as_utc(parsed)
                else:
                    self._native_value = state.state
            if restored_end is None:
                end_time = state.attributes.get("end_time")
                if isinstance(end_time, str):
                    parsed_end = dt_util.parse_datetime(end_time)
                    if parsed_end is not None:
                        restored_end = dt_util.as_utc(parsed_end)

        registry = await async_get_timer_registry(self.hass)
        self._timer = await registry.async_get_timer(
            self._entry.entry_id,
            self._data[CONF_THERMOSTAT],
            self._data[DATA_THERMOSTAT_NAME],
        )
        await self._async_restore_missing_timer(restored_end)
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

    async def _async_restore_missing_timer(self, restored_end: datetime | None) -> None:
        """Recreate timer from restored sensor state if storage was unavailable."""
        if self._timer is None or restored_end is None:
            return
        if self._timer.snapshot().end is not None:
            return
        now = dt_util.utcnow()
        if restored_end <= now:
            return
        await self._timer.async_start(restored_end - now)

    async def async_start_boost(
        self,
        time: dict | str | None = None,
        temperature_c: float | None = None,
    ) -> None:
        """Start boost: set temperature, start timer, mark active."""
        await async_start_boost_for_entry(
            self.hass, self._entry.entry_id, time=time, temperature_c=temperature_c
        )

    async def async_finish_boost(self) -> None:
        """Finish boost: clear timer, reset temperature, mark inactive."""
        await async_finish_boost_for_entry(self.hass, self._entry.entry_id)


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


def _normalize_to_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _entry_id_from_unique_id(unique_id: str) -> str | None:
    for suffix in (
        UNIQUE_ID_BOOST_FINISH,
        UNIQUE_ID_BOOST_ACTIVE,
        UNIQUE_ID_BOOST_TEMPERATURE,
        UNIQUE_ID_SCHEDULE_OVERRIDE,
        UNIQUE_ID_TIME_SELECTOR,
    ):
        token = f"_{suffix}"
        if unique_id.endswith(token):
            return unique_id[: -len(token)]
    return None


@callback
def _entry_id_from_entity_id(hass: HomeAssistant, entity_id: str) -> str | None:
    entity_reg = er.async_get(hass)
    reg_entry = entity_reg.async_get(entity_id)
    if reg_entry is None:
        return None
    unique_id = reg_entry.unique_id or ""
    return _entry_id_from_unique_id(unique_id)


@callback
def _entry_id_from_device_id(hass: HomeAssistant, device_id: str) -> str | None:
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id in domain_data:
        if entry_id in ("timer_services_registered", "start_boost_service_registered"):
            continue
        finish_entity_id = _get_entity_id(hass, entry_id, UNIQUE_ID_BOOST_FINISH)
        if not finish_entity_id:
            continue
        entity_reg = er.async_get(hass)
        reg_entry = entity_reg.async_get(finish_entity_id)
        if reg_entry is not None and reg_entry.device_id == device_id:
            return entry_id
    return None


async def async_start_boost_for_entry(
    hass: HomeAssistant,
    entry_id: str,
    *,
    time: dict | str | None = None,
    temperature_c: float | None = None,
) -> None:
    _LOGGER.debug(
        "Start boost started for %s (requested_time=%s, requested_temperature_c=%s)",
        entry_id,
        time,
        temperature_c,
    )

    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not data:
        _LOGGER.debug("Start boost aborted for %s: config entry not found", entry_id)
        raise HomeAssistantError(f"No thermostat_boost entry found for {entry_id}")

    registry = await async_get_timer_registry(hass)
    timer = await registry.async_get_timer(
        entry_id,
        data[CONF_THERMOSTAT],
        data[DATA_THERMOSTAT_NAME],
    )
    boost_was_active = _is_switch_on(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE)
    schedule_override_active = _is_switch_on(
        hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE
    )
    _LOGGER.debug(
        "Start boost pre-check for %s: boost_was_active=%s, schedule_override_active=%s",
        entry_id,
        boost_was_active,
        schedule_override_active,
    )
    if not boost_was_active:
        scheduler_switches = get_scheduler_switches_for_thermostat(
            hass, data[DATA_THERMOSTAT_NAME]
        )
        no_schedules_defined = not scheduler_switches
        stored_temperature = await async_store_target_temperature_snapshot(
            hass,
            entry_id,
            data[CONF_THERMOSTAT],
        )
        _LOGGER.debug(
            "Start boost schedule check for %s: "
            "schedule_override_active=%s, no_schedules_detected=%s, "
            "stored_temperature_snapshot=%s",
            entry_id,
            schedule_override_active,
            no_schedules_defined,
            stored_temperature,
        )

    if temperature_c is None:
        temperature_c = _get_number_value(hass, entry_id, UNIQUE_ID_BOOST_TEMPERATURE)
    if temperature_c is None:
        _LOGGER.debug(
            "Start boost aborted for %s: no boost temperature value available",
            entry_id,
        )
        raise HomeAssistantError("Unable to determine boost temperature.")

    if time is None:
        duration_hours = _get_number_value(hass, entry_id, UNIQUE_ID_TIME_SELECTOR)
        if duration_hours is None:
            duration_hours = 0.0
        duration = timedelta(hours=float(duration_hours))
    else:
        duration = _parse_duration_value(time)
    _LOGGER.debug(
        "Start boost resolved inputs for %s: temperature_c=%s, duration=%s",
        entry_id,
        temperature_c,
        duration,
    )

    target_temp = temperature_c
    if hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
        target_temp = TemperatureConverter.convert(
            temperature_c,
            UnitOfTemperature.CELSIUS,
            hass.config.units.temperature_unit,
        )

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {
            "entity_id": data[CONF_THERMOSTAT],
            "temperature": target_temp,
        },
        blocking=True,
    )
    _LOGGER.debug(
        "Start boost step complete for %s: target temperature applied "
        "(thermostat=%s, target=%s %s)",
        entry_id,
        data[CONF_THERMOSTAT],
        target_temp,
        hass.config.units.temperature_unit,
    )

    await timer.async_start(duration)
    _LOGGER.debug(
        "Start boost step complete for %s: timer started (end=%s)",
        entry_id,
        timer.snapshot().end,
    )

    boost_active_entity_id = _get_entity_id(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE)
    if boost_active_entity_id:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": boost_active_entity_id},
            blocking=True,
        )
        _LOGGER.debug(
            "Start boost step complete for %s: boost marked active (entity_id=%s)",
            entry_id,
            boost_active_entity_id,
        )

    if not boost_was_active and not schedule_override_active:
        scheduler_switches = await async_create_scheduler_scene(
            hass, entry_id, data[DATA_THERMOSTAT_NAME]
        )
        if scheduler_switches:
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": scheduler_switches},
                blocking=True,
            )
            _LOGGER.debug(
                "Start boost step complete for %s: scheduler state snapshotted and "
                "scheduler switches turned off: %s",
                entry_id,
                scheduler_switches,
            )
        else:
            _LOGGER.debug(
                "Start boost scheduler snapshot step skipped for %s: "
                "no matching scheduler switches found",
                entry_id,
            )


def _parse_duration_value(value) -> timedelta:
    """Parse duration from selector object or HH:MM:SS string and reject zero."""
    if isinstance(value, dict):
        duration = timedelta(
            days=int(value.get("days", 0) or 0),
            hours=int(value.get("hours", 0) or 0),
            minutes=int(value.get("minutes", 0) or 0),
            seconds=int(value.get("seconds", 0) or 0),
            milliseconds=int(value.get("milliseconds", 0) or 0),
        )
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) != 3:
            raise HomeAssistantError("time must be in HH:MM:SS format.")
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        except (TypeError, ValueError):
            raise HomeAssistantError("time must be in HH:MM:SS format.") from None
        if minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59 or hours < 0:
            raise HomeAssistantError("time must be in HH:MM:SS format.")
        duration = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    else:
        raise HomeAssistantError("time must be a duration selector value.")

    if duration.total_seconds() <= 0:
        raise HomeAssistantError("time cannot be 00:00:00.")
    return duration


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
