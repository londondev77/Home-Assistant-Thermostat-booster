"""Shared boost actions."""

from __future__ import annotations

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
from .timer_manager import async_get_timer_registry

_SNAPSHOT_STORAGE_VERSION = 1
_SNAPSHOT_STORAGE_KEY = f"{DOMAIN}.scheduler_snapshot"
_SNAPSHOT_RESTORE_RETRY_DELAY = 15
_SNAPSHOT_RESTORE_PENDING_KEY = "snapshot_restore_pending"
_SNAPSHOT_RETRIGGER_DELAY = 10
_SNAPSHOT_RETRIGGER_PENDING_KEY = "snapshot_retrigger_pending"


def _matches_tag(tags, thermostat_name: str) -> bool:
    if tags is None:
        return False
    if isinstance(tags, str):
        return thermostat_name.lower() in tags.lower()
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and thermostat_name.lower() in tag.lower():
                return True
    return False


def _get_scheduler_switches(hass: HomeAssistant, thermostat_name: str) -> list[str]:
    """Return scheduler switch entity_ids matching the thermostat tag."""
    entity_reg = er.async_get(hass)
    scheduler_entities = [
        entry.entity_id
        for entry in entity_reg.entities.values()
        if entry.domain == "switch" and (entry.platform or "").lower() == "scheduler"
    ]

    matched: list[str] = []
    for entity_id in scheduler_entities:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            continue
        if _matches_tag(state.attributes.get("tags"), thermostat_name):
            matched.append(entity_id)
    return matched


async def _load_snapshot_store(
    hass: HomeAssistant,
) -> tuple[Store, dict[str, dict[str, str]]]:
    store = Store(hass, _SNAPSHOT_STORAGE_VERSION, _SNAPSHOT_STORAGE_KEY)
    data = await store.async_load() or {}
    return store, data


def _get_snapshot_restore_pending(hass: HomeAssistant) -> set[str]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RESTORE_PENDING_KEY, set())


def _get_snapshot_retrigger_pending(hass: HomeAssistant) -> set[str]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RETRIGGER_PENDING_KEY, set())


def _schedule_snapshot_restore_retry(hass: HomeAssistant, entry_id: str) -> None:
    pending = _get_snapshot_restore_pending(hass)
    if entry_id in pending:
        return
    pending.add(entry_id)

    @callback
    def _retry(_now) -> None:
        pending.discard(entry_id)
        hass.add_job(async_restore_scheduler_snapshot(hass, entry_id))

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
    except HomeAssistantError:
        pass


async def async_create_scheduler_scene(
    hass: HomeAssistant, entry_id: str, thermostat_name: str
) -> list[str]:
    """Persist scheduler switch states and return the entity_ids."""
    scheduler_switches = _get_scheduler_switches(hass, thermostat_name)
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


async def async_restore_scheduler_snapshot(hass: HomeAssistant, entry_id: str) -> None:
    """Restore scheduler switch states from persistent storage."""
    store, data = await _load_snapshot_store(hass)
    snapshot = data.get(entry_id)
    if snapshot is None:
        _get_snapshot_restore_pending(hass).discard(entry_id)
        return

    if not snapshot:
        data.pop(entry_id, None)
        await store.async_save(data)
        _get_snapshot_restore_pending(hass).discard(entry_id)
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
        _schedule_snapshot_restore_retry(hass, entry_id)
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
    except HomeAssistantError:
        _schedule_snapshot_restore_retry(hass, entry_id)
        return

    data.pop(entry_id, None)
    await store.async_save(data)
    _get_snapshot_restore_pending(hass).discard(entry_id)
    _schedule_scheduler_retrigger(hass, entry_id, to_turn_on)


async def async_clear_scheduler_snapshot(hass: HomeAssistant, entry_id: str) -> None:
    """Clear stored scheduler snapshot for an entry."""
    store, data = await _load_snapshot_store(hass)
    if entry_id in data:
        data.pop(entry_id, None)
        await store.async_save(data)
    _get_snapshot_restore_pending(hass).discard(entry_id)
    _get_snapshot_retrigger_pending(hass).discard(entry_id)


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

    if not _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE):
        await async_restore_scheduler_snapshot(hass, entry_id)


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
