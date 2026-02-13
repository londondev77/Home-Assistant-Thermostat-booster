"""Shared boost actions."""

from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_SCHEDULE_OVERRIDE,
    UNIQUE_ID_TIME_SELECTOR,
)
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from .scheduler_utils import get_scheduler_switches_for_thermostat
from .timer_manager import async_get_timer_registry

_SNAPSHOT_STORAGE_VERSION = 1
_SNAPSHOT_STORAGE_KEY = f"{DOMAIN}.scheduler_snapshot"
_SNAPSHOT_RESTORE_RETRY_DELAY = 15
_SNAPSHOT_RESTORE_PENDING_KEY = "snapshot_restore_pending"
_SNAPSHOT_RETRIGGER_DELAY = 10
_SNAPSHOT_RETRIGGER_PENDING_KEY = "snapshot_retrigger_pending"
_TEMP_SNAPSHOT_STORAGE_VERSION = 1
_TEMP_SNAPSHOT_STORAGE_KEY = f"{DOMAIN}.temperature_snapshot"
_LOGGER = logging.getLogger(__name__)


async def _load_snapshot_store(
    hass: HomeAssistant,
) -> tuple[Store, dict[str, dict[str, str]]]:
    store = Store(hass, _SNAPSHOT_STORAGE_VERSION, _SNAPSHOT_STORAGE_KEY)
    data = await store.async_load() or {}
    return store, data


async def _load_temperature_snapshot_store(
    hass: HomeAssistant,
) -> tuple[Store, dict[str, float]]:
    store = Store(hass, _TEMP_SNAPSHOT_STORAGE_VERSION, _TEMP_SNAPSHOT_STORAGE_KEY)
    data = await store.async_load() or {}
    return store, data


def _get_snapshot_restore_pending(hass: HomeAssistant) -> dict[str, bool]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RESTORE_PENDING_KEY, {})


def _get_snapshot_retrigger_pending(hass: HomeAssistant) -> set[str]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RETRIGGER_PENDING_KEY, set())


def _schedule_snapshot_restore_retry(
    hass: HomeAssistant, entry_id: str, *, allow_retrigger: bool
) -> None:
    pending = _get_snapshot_restore_pending(hass)
    pending[entry_id] = bool(pending.get(entry_id)) or allow_retrigger
    _LOGGER.debug(
        "Scheduling scheduler snapshot restore retry for %s (allow_retrigger=%s)",
        entry_id,
        pending[entry_id],
    )

    @callback
    def _retry(_now) -> None:
        allow = bool(pending.pop(entry_id, False))
        hass.add_job(
            async_restore_scheduler_snapshot(
                hass,
                entry_id,
                allow_retrigger=allow,
            )
        )

    async_call_later(hass, _SNAPSHOT_RESTORE_RETRY_DELAY, _retry)


def _schedule_scheduler_retrigger(
    hass: HomeAssistant, entry_id: str, to_turn_on: list[str]
) -> None:
    pending = _get_snapshot_retrigger_pending(hass)
    if entry_id in pending:
        return

    target_entities = sorted({entity_id for entity_id in to_turn_on if entity_id})
    if not target_entities:
        return
    pending.add(entry_id)

    @callback
    def _retry(_now) -> None:
        pending.discard(entry_id)
        hass.add_job(
            _async_retrigger_scheduler_switches(hass, entry_id, target_entities)
        )

    async_call_later(hass, _SNAPSHOT_RETRIGGER_DELAY, _retry)


async def _async_retrigger_scheduler_switches(
    hass: HomeAssistant, entry_id: str, entity_ids: list[str]
) -> None:
    # Retrigger is only valid immediately after boost-end restore.
    if _is_switch_on(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE):
        return
    if _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE):
        return

    available_entities = [
        entity_id
        for entity_id in entity_ids
        if (
            (state := hass.states.get(entity_id)) is not None
            and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        )
    ]
    if not available_entities:
        return

    try:
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": available_entities},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": available_entities},
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.warning(
            "Scheduler retrigger failed for %s on %s: %s",
            entry_id,
            available_entities,
            err,
        )


async def async_create_scheduler_scene(
    hass: HomeAssistant, entry_id: str, thermostat_name: str
) -> list[str]:
    """Persist scheduler switch states and return the entity_ids."""
    scheduler_switches = get_scheduler_switches_for_thermostat(hass, thermostat_name)
    if not scheduler_switches:
        return []

    snapshot: dict[str, str] = {}
    for entity_id in scheduler_switches:
        state = hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            continue
        snapshot[entity_id] = state.state

    store, data = await _load_snapshot_store(hass)
    data[entry_id] = snapshot
    await store.async_save(data)
    return list(snapshot.keys())


async def async_restore_scheduler_snapshot(
    hass: HomeAssistant, entry_id: str, *, allow_retrigger: bool = False
) -> None:
    """Restore scheduler switch states from persistent storage."""
    # Do not restore schedules while boost or override is active.
    if _is_switch_on(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE):
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Skipping scheduler snapshot restore for %s because boost is active",
            entry_id,
        )
        return
    if _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE):
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Skipping scheduler snapshot restore for %s because schedule override is active",
            entry_id,
        )
        return

    store, data = await _load_snapshot_store(hass)
    snapshot = data.get(entry_id)
    if snapshot is None:
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        return

    if not snapshot:
        data.pop(entry_id, None)
        await store.async_save(data)
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        return

    missing_entities = [
        entity_id
        for entity_id in snapshot
        if (
            (state := hass.states.get(entity_id)) is None
            or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        )
    ]
    if missing_entities:
        _LOGGER.debug(
            "Deferring scheduler snapshot restore for %s; unavailable entities: %s",
            entry_id,
            missing_entities,
        )
        _schedule_snapshot_restore_retry(
            hass,
            entry_id,
            allow_retrigger=allow_retrigger,
        )
        return

    to_turn_on = [entity_id for entity_id, state in snapshot.items() if state == "on"]
    to_turn_off = [entity_id for entity_id, state in snapshot.items() if state != "on"]

    try:
        if to_turn_on:
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": to_turn_on},
                blocking=True,
            )
        if to_turn_off:
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": to_turn_off},
                blocking=True,
            )
    except HomeAssistantError as err:
        _LOGGER.warning(
            "Scheduler snapshot restore failed for %s (on=%s, off=%s): %s",
            entry_id,
            to_turn_on,
            to_turn_off,
            err,
        )
        _schedule_snapshot_restore_retry(
            hass,
            entry_id,
            allow_retrigger=allow_retrigger,
        )
        return

    data.pop(entry_id, None)
    await store.async_save(data)
    _get_snapshot_restore_pending(hass).pop(entry_id, None)
    if allow_retrigger:
        _schedule_scheduler_retrigger(hass, entry_id, to_turn_on)


async def async_clear_scheduler_snapshot(hass: HomeAssistant, entry_id: str) -> None:
    """Clear stored scheduler snapshot for an entry."""
    store, data = await _load_snapshot_store(hass)
    if entry_id in data:
        data.pop(entry_id, None)
        await store.async_save(data)
    _get_snapshot_restore_pending(hass).pop(entry_id, None)
    _get_snapshot_retrigger_pending(hass).discard(entry_id)


@callback
def _get_current_target_temperature(
    hass: HomeAssistant, thermostat_entity_id: str
) -> float | None:
    state = hass.states.get(thermostat_entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    value = state.attributes.get("temperature")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_store_target_temperature_snapshot(
    hass: HomeAssistant, entry_id: str, thermostat_entity_id: str
) -> bool:
    """Persist current thermostat target temperature for later restore."""
    temperature = _get_current_target_temperature(hass, thermostat_entity_id)
    if temperature is None:
        _LOGGER.debug(
            "No target temperature available to snapshot for %s (%s)",
            entry_id,
            thermostat_entity_id,
        )
        return False

    store, data = await _load_temperature_snapshot_store(hass)
    data[entry_id] = temperature
    await store.async_save(data)
    _LOGGER.debug(
        "Stored target temperature snapshot for %s (%s): %s",
        entry_id,
        thermostat_entity_id,
        temperature,
    )
    return True


async def async_restore_target_temperature_snapshot(
    hass: HomeAssistant, entry_id: str, thermostat_entity_id: str
) -> bool:
    """Restore thermostat target temperature from persistent storage."""
    store, data = await _load_temperature_snapshot_store(hass)
    if entry_id not in data:
        _LOGGER.debug(
            "No target temperature snapshot found for %s",
            entry_id,
        )
        return False

    try:
        temperature = float(data[entry_id])
    except (TypeError, ValueError) as err:
        _LOGGER.warning(
            "Invalid target temperature snapshot for %s (%s): %s",
            entry_id,
            data.get(entry_id),
            err,
        )
        data.pop(entry_id, None)
        await store.async_save(data)
        return False

    try:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": thermostat_entity_id,
                "temperature": temperature,
            },
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.warning(
            "Failed to restore target temperature for %s (%s): %s",
            entry_id,
            thermostat_entity_id,
            err,
        )
        return False

    data.pop(entry_id, None)
    await store.async_save(data)
    _LOGGER.debug(
        "Restored target temperature snapshot for %s (%s): %s",
        entry_id,
        thermostat_entity_id,
        temperature,
    )
    return True


async def async_clear_target_temperature_snapshot(
    hass: HomeAssistant, entry_id: str
) -> None:
    """Clear stored target-temperature snapshot for an entry."""
    store, data = await _load_temperature_snapshot_store(hass)
    if entry_id in data:
        data.pop(entry_id, None)
        await store.async_save(data)
        _LOGGER.debug("Cleared target temperature snapshot for %s", entry_id)


@callback
def _get_entity_id(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> str | None:
    entity_reg = er.async_get(hass)
    unique_id = f"{entry_id}_{unique_id_suffix}"
    for entry in entity_reg.entities.values():
        if entry.unique_id == unique_id:
            return entry.entity_id
    return None


async def async_finish_boost_for_entry(hass: HomeAssistant, entry_id: str) -> None:
    """Finish boost for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not data:
        return

    registry = await async_get_timer_registry(hass)
    timer = await registry.async_get_timer(
        entry_id,
        data[CONF_THERMOSTAT],
        data[DATA_THERMOSTAT_NAME],
    )
    await timer.async_cancel()

    time_selector_entity_id = _get_entity_id(
        hass, entry_id, UNIQUE_ID_TIME_SELECTOR
    )
    if time_selector_entity_id:
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": time_selector_entity_id, "value": 0},
            blocking=True,
        )

    boost_active_entity_id = _get_entity_id(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE)
    if boost_active_entity_id:
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": boost_active_entity_id},
            blocking=True,
        )

    thermostat_name = data[DATA_THERMOSTAT_NAME]
    schedule_override_active = _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE)
    scheduler_switches = get_scheduler_switches_for_thermostat(hass, thermostat_name)
    no_schedules_defined = not scheduler_switches

    if schedule_override_active or no_schedules_defined:
        restored = await async_restore_target_temperature_snapshot(
            hass,
            entry_id,
            data[CONF_THERMOSTAT],
        )
        if not restored:
            _LOGGER.debug(
                "No target temperature snapshot restored for %s during finish_boost "
                "(override_active=%s, no_schedules_defined=%s)",
                entry_id,
                schedule_override_active,
                no_schedules_defined,
            )
        return

    await async_clear_target_temperature_snapshot(hass, entry_id)
    await async_restore_scheduler_snapshot(hass, entry_id, allow_retrigger=True)


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
