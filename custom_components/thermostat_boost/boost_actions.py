"""Shared boost actions."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

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
from .scheduler_utils import (
    get_scheduler_switches_for_thermostat,
)
from .timer_manager import async_get_timer_registry

_SNAPSHOT_STORAGE_VERSION = 1
_SNAPSHOT_STORAGE_KEY = f"{DOMAIN}.scheduler_snapshot"
_SNAPSHOT_RESTORE_RETRY_DELAY = 15
_SNAPSHOT_RESTORE_STABILIZE_DELAY = 0
_SNAPSHOT_RESTORE_PENDING_KEY = "snapshot_restore_pending"
_SNAPSHOT_RESTORE_UNSUB_KEY = "snapshot_restore_unsub"
_SNAPSHOT_STABILIZE_PENDING_KEY = "snapshot_stabilize_pending"
_SNAPSHOT_STABILIZE_UNSUB_KEY = "snapshot_stabilize_unsub"
_SNAPSHOT_RETRIGGER_DELAY = 0
_SNAPSHOT_RETRIGGER_STEP_DELAY = 10
_SNAPSHOT_RETRIGGER_PENDING_KEY = "snapshot_retrigger_pending"
_SNAPSHOT_RETRIGGER_UNSUB_KEY = "snapshot_retrigger_unsub"
_FINISH_IN_PROGRESS_KEY = "finish_in_progress"
_TEMP_SNAPSHOT_STORAGE_VERSION = 1
_TEMP_SNAPSHOT_STORAGE_KEY = f"{DOMAIN}.temperature_snapshot"
_LOGGER = logging.getLogger(__name__)

# Current active behavior summary:
# - Start boost:
#   - On first start (when boost was not already active), store a pre-boost
#     target-temperature snapshot.
# - Finish boost with scheduler snapshot:
#   - Restore pre-boost target temperature snapshot first (if present).
#   - Restore scheduler switches from snapshot.
#   - Run scheduler.run_action for schedules restored to ON.
#   - Scheduler action then determines the effective target temperature.
# - Offline-expiry path:
#   - Restores schedules with availability retry safeguards.
#   - Calls scheduler.run_action for restored ON schedules.
# - Retrigger helpers remain in file for rollback/tuning, but are not currently used
#   by the active offline-expiry finish path.


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


def _get_snapshot_restore_unsub(
    hass: HomeAssistant,
) -> dict[str, Callable[[], None]]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RESTORE_UNSUB_KEY, {})


def _get_snapshot_retrigger_unsub(
    hass: HomeAssistant,
) -> dict[str, Callable[[], None]]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_RETRIGGER_UNSUB_KEY, {})


def _get_snapshot_stabilize_pending(hass: HomeAssistant) -> set[str]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_STABILIZE_PENDING_KEY, set())


def _get_snapshot_stabilize_unsub(
    hass: HomeAssistant,
) -> dict[str, Callable[[], None]]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_SNAPSHOT_STABILIZE_UNSUB_KEY, {})


def _get_finish_in_progress(hass: HomeAssistant) -> set[str]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_FINISH_IN_PROGRESS_KEY, set())


@callback
def async_cancel_pending_scheduler_callbacks(hass: HomeAssistant, entry_id: str) -> None:
    """Cancel pending delayed scheduler callbacks for an entry."""
    restore_unsubs = _get_snapshot_restore_unsub(hass)
    retrigger_unsubs = _get_snapshot_retrigger_unsub(hass)
    stabilize_unsubs = _get_snapshot_stabilize_unsub(hass)

    restore_cancelled = False
    if (unsub := restore_unsubs.pop(entry_id, None)) is not None:
        unsub()
        restore_cancelled = True

    retrigger_cancelled = False
    if (unsub := retrigger_unsubs.pop(entry_id, None)) is not None:
        unsub()
        retrigger_cancelled = True

    stabilize_cancelled = False
    if (unsub := stabilize_unsubs.pop(entry_id, None)) is not None:
        unsub()
        stabilize_cancelled = True

    _get_snapshot_restore_pending(hass).pop(entry_id, None)
    _get_snapshot_stabilize_pending(hass).discard(entry_id)
    _get_snapshot_retrigger_pending(hass).discard(entry_id)

    if restore_cancelled or retrigger_cancelled or stabilize_cancelled:
        _LOGGER.debug(
            "Cancelled pending scheduler callbacks for %s "
            "(restore=%s, stabilize=%s, retrigger=%s)",
            entry_id,
            restore_cancelled,
            stabilize_cancelled,
            retrigger_cancelled,
        )


def _schedule_snapshot_restore_retry(
    hass: HomeAssistant, entry_id: str, *, expired_while_offline: bool
) -> None:
    pending = _get_snapshot_restore_pending(hass)
    pending[entry_id] = bool(pending.get(entry_id)) or expired_while_offline

    restore_unsubs = _get_snapshot_restore_unsub(hass)
    if entry_id in restore_unsubs:
        _LOGGER.debug(
            "Scheduler restore retry already queued for %s "
            "(merged_expired_while_offline=%s)",
            entry_id,
            pending[entry_id],
        )
        return

    _LOGGER.debug(
        "Queueing scheduler restore retry for %s in %ss (expired_while_offline=%s)",
        entry_id,
        _SNAPSHOT_RESTORE_RETRY_DELAY,
        pending[entry_id],
    )

    @callback
    def _retry(_now) -> None:
        restore_unsubs.pop(entry_id, None)
        expired_offline = bool(pending.pop(entry_id, False))
        hass.add_job(
            async_restore_scheduler_snapshot(
                hass,
                entry_id,
                expired_while_offline=expired_offline,
            )
        )

    restore_unsubs[entry_id] = async_call_later(
        hass, _SNAPSHOT_RESTORE_RETRY_DELAY, _retry
    )


def _schedule_scheduler_retrigger(
    hass: HomeAssistant, entry_id: str, to_turn_on: list[str]
) -> None:
    pending = _get_snapshot_retrigger_pending(hass)
    retrigger_unsubs = _get_snapshot_retrigger_unsub(hass)
    if entry_id in pending or entry_id in retrigger_unsubs:
        _LOGGER.debug(
            "Scheduler retrigger already queued for %s; skipping duplicate request",
            entry_id,
        )
        return

    target_entities = sorted({entity_id for entity_id in to_turn_on if entity_id})
    if not target_entities:
        _LOGGER.debug(
            "Scheduler retrigger skipped for %s: no ON-state entities to retrigger",
            entry_id,
        )
        return
    pending.add(entry_id)
    _LOGGER.debug(
        "Queueing scheduler retrigger for %s in %ss (offline-expiry mitigation): %s",
        entry_id,
        _SNAPSHOT_RETRIGGER_DELAY,
        target_entities,
    )

    @callback
    def _retry(_now) -> None:
        pending.discard(entry_id)
        retrigger_unsubs.pop(entry_id, None)
        _LOGGER.debug(
            "Running queued scheduler retrigger for %s: %s",
            entry_id,
            target_entities,
        )
        hass.add_job(
            _async_retrigger_scheduler_switches(hass, entry_id, target_entities)
        )

    retrigger_unsubs[entry_id] = async_call_later(
        hass, _SNAPSHOT_RETRIGGER_DELAY, _retry
    )


async def _async_retrigger_scheduler_switches(
    hass: HomeAssistant, entry_id: str, entity_ids: list[str]
) -> None:
    # Retrigger is only valid immediately after boost-end restore.
    if _is_switch_on(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE):
        _LOGGER.debug(
            "Scheduler retrigger skipped for %s: boost is active at execution time",
            entry_id,
        )
        return
    if _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE):
        _LOGGER.debug(
            "Scheduler retrigger skipped for %s: schedule override is active at execution time",
            entry_id,
        )
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
        _LOGGER.debug(
            "Scheduler retrigger skipped for %s: no currently available entities from %s",
            entry_id,
            entity_ids,
        )
        return

    try:
        _LOGGER.debug(
            "Scheduler retrigger step 1/2 (turn_off) for %s: %s",
            entry_id,
            available_entities,
        )
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": available_entities},
            blocking=True,
        )
        _LOGGER.debug(
            "Scheduler retrigger step 1/2 complete for %s: %s",
            entry_id,
            available_entities,
        )
        _LOGGER.debug(
            "Scheduler retrigger waiting %ss before step 2/2 for %s",
            _SNAPSHOT_RETRIGGER_STEP_DELAY,
            entry_id,
        )
        await asyncio.sleep(_SNAPSHOT_RETRIGGER_STEP_DELAY)
        _LOGGER.debug(
            "Scheduler retrigger step 2/2 (turn_on) for %s: %s",
            entry_id,
            available_entities,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": available_entities},
            blocking=True,
        )
        _LOGGER.debug(
            "Scheduler retrigger step 2/2 complete for %s: %s",
            entry_id,
            available_entities,
        )
    except HomeAssistantError as err:
        _LOGGER.warning(
            "Scheduler retrigger failed for %s on %s: %s",
            entry_id,
            available_entities,
            err,
        )


async def _async_run_scheduler_actions(
    hass: HomeAssistant, entry_id: str, entity_ids: list[str]
) -> None:
    """Run Scheduler actions for restored ON-state schedule switches."""
    target_entities = sorted({entity_id for entity_id in entity_ids if entity_id})
    if not target_entities:
        return

    for entity_id in target_entities:
        try:
            _LOGGER.debug(
                "Scheduler run_action started for %s via %s",
                entry_id,
                entity_id,
            )
            await hass.services.async_call(
                "scheduler",
                "run_action",
                {"entity_id": entity_id},
                blocking=True,
            )
            _LOGGER.debug(
                "Scheduler run_action completed for %s via %s",
                entry_id,
                entity_id,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Scheduler run_action failed for %s via %s: %s",
                entry_id,
                entity_id,
                err,
            )


async def async_create_scheduler_scene(
    hass: HomeAssistant, entry_id: str, thermostat_name: str
) -> list[str]:
    """Persist scheduler switch states and return the entity_ids."""
    scheduler_switches = get_scheduler_switches_for_thermostat(hass, thermostat_name)
    if not scheduler_switches:
        _LOGGER.debug(
            "No scheduler switches found to snapshot for %s (%s)",
            entry_id,
            thermostat_name,
        )
        return []

    snapshot: dict[str, str] = {}
    for entity_id in scheduler_switches:
        state = hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            continue
        snapshot[entity_id] = state.state
    _LOGGER.debug(
        "Captured scheduler snapshot for %s: %s",
        entry_id,
        snapshot,
    )

    store, data = await _load_snapshot_store(hass)
    data[entry_id] = snapshot
    await store.async_save(data)
    return list(snapshot.keys())


async def async_restore_scheduler_snapshot(
    hass: HomeAssistant,
    entry_id: str,
    *,
    expired_while_offline: bool = False,
    skip_stabilize_delay: bool = False,
) -> None:
    """Restore scheduler switch states from persistent storage."""
    # Do not restore schedules while boost or override is active.
    if _is_switch_on(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE):
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Scheduler restore skipped for %s: boost is currently active",
            entry_id,
        )
        return
    if _is_switch_on(hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE):
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Scheduler restore skipped for %s: schedule override is currently active",
            entry_id,
        )
        return

    store, data = await _load_snapshot_store(hass)
    snapshot = data.get(entry_id)
    if snapshot is None:
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Scheduler restore skipped for %s: no stored scheduler snapshot",
            entry_id,
        )
        return

    if not snapshot:
        data.pop(entry_id, None)
        await store.async_save(data)
        _get_snapshot_restore_pending(hass).pop(entry_id, None)
        _LOGGER.debug(
            "Scheduler restore for %s found an empty snapshot; cleared stored entry",
            entry_id,
        )
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
            "Deferring scheduler restore for %s; entities unavailable: %s",
            entry_id,
            missing_entities,
        )
        _schedule_snapshot_restore_retry(
            hass,
            entry_id,
            expired_while_offline=expired_while_offline,
        )
        return

    # Offline-expiry only: once entities are available, wait briefly before restore.
    if expired_while_offline and not skip_stabilize_delay:
        stabilize_pending = _get_snapshot_stabilize_pending(hass)
        stabilize_unsubs = _get_snapshot_stabilize_unsub(hass)
        if entry_id in stabilize_pending or entry_id in stabilize_unsubs:
            _LOGGER.debug(
                "Scheduler stabilize wait already queued for %s; skipping duplicate request",
                entry_id,
            )
            return

        stabilize_pending.add(entry_id)
        _LOGGER.debug(
            "Waiting %ss before restoring schedules for %s",
            _SNAPSHOT_RESTORE_STABILIZE_DELAY,
            entry_id,
        )

        @callback
        def _stabilized_restore(_now) -> None:
            stabilize_pending.discard(entry_id)
            stabilize_unsubs.pop(entry_id, None)
            hass.add_job(
                async_restore_scheduler_snapshot(
                    hass,
                    entry_id,
                    expired_while_offline=expired_while_offline,
                    skip_stabilize_delay=True,
                )
            )

        stabilize_unsubs[entry_id] = async_call_later(
            hass, _SNAPSHOT_RESTORE_STABILIZE_DELAY, _stabilized_restore
        )
        return

    to_turn_on = [entity_id for entity_id, state in snapshot.items() if state == "on"]
    to_turn_off = [entity_id for entity_id, state in snapshot.items() if state != "on"]
    _LOGGER.debug(
        "Scheduler restore executing for %s: turn_on=%s, turn_off=%s",
        entry_id,
        to_turn_on,
        to_turn_off,
    )

    try:
        if to_turn_on:
            _LOGGER.debug(
                "Scheduler restore action (turn_on) started for %s: %s",
                entry_id,
                to_turn_on,
            )
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": to_turn_on},
                blocking=True,
            )
            _LOGGER.debug(
                "Scheduler restore action (turn_on) completed for %s: %s",
                entry_id,
                to_turn_on,
            )
        if to_turn_off:
            _LOGGER.debug(
                "Scheduler restore action (turn_off) started for %s: %s",
                entry_id,
                to_turn_off,
            )
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": to_turn_off},
                blocking=True,
            )
            _LOGGER.debug(
                "Scheduler restore action (turn_off) completed for %s: %s",
                entry_id,
                to_turn_off,
            )
        # Run scheduler actions for restored ON schedules so scheduler can re-apply
        # effective setpoints after switches are restored.
        if to_turn_on:
            await _async_run_scheduler_actions(hass, entry_id, to_turn_on)
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
            expired_while_offline=expired_while_offline,
        )
        return

    data.pop(entry_id, None)
    await store.async_save(data)
    _get_snapshot_restore_pending(hass).pop(entry_id, None)
    _LOGGER.debug("Scheduler restore completed successfully for %s", entry_id)
    if expired_while_offline:
        _LOGGER.debug(
            "Scheduler restore for %s completed in offline-expiry mode; "
            "retrigger path disabled",
            entry_id,
        )


async def async_clear_scheduler_snapshot(hass: HomeAssistant, entry_id: str) -> None:
    """Clear stored scheduler snapshot for an entry."""
    store, data = await _load_snapshot_store(hass)
    if entry_id in data:
        data.pop(entry_id, None)
        await store.async_save(data)
    async_cancel_pending_scheduler_callbacks(hass, entry_id)


async def _has_scheduler_snapshot(hass: HomeAssistant, entry_id: str) -> bool:
    """Return whether a scheduler snapshot exists for this entry."""
    _store, data = await _load_snapshot_store(hass)
    return entry_id in data


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
) -> float | None:
    """Persist current thermostat target temperature for later restore."""
    temperature = _get_current_target_temperature(hass, thermostat_entity_id)
    if temperature is None:
        _LOGGER.debug(
            "No target temperature available to snapshot for %s (%s)",
            entry_id,
            thermostat_entity_id,
        )
        return None

    store, data = await _load_temperature_snapshot_store(hass)
    data[entry_id] = temperature
    await store.async_save(data)
    _LOGGER.debug(
        "Stored target temperature snapshot for %s (%s): %s",
        entry_id,
        thermostat_entity_id,
        temperature,
    )
    return temperature


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


async def async_finish_boost_for_entry(
    hass: HomeAssistant, entry_id: str, *, expired_while_offline: bool = False
) -> None:
    """Finish boost for a config entry."""
    finish_in_progress = _get_finish_in_progress(hass)
    if entry_id in finish_in_progress:
        _LOGGER.debug(
            "Finish boost request ignored for %s: another finish is already running",
            entry_id,
        )
        return
    finish_in_progress.add(entry_id)

    try:
        _LOGGER.debug(
            "Finish boost started for %s (expired_while_offline=%s)",
            entry_id,
            expired_while_offline,
        )
        data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not data:
            _LOGGER.debug("Finish boost skipped for %s: entry not found", entry_id)
            return

        registry = await async_get_timer_registry(hass)
        timer = await registry.async_get_timer(
            entry_id,
            data[CONF_THERMOSTAT],
            data[DATA_THERMOSTAT_NAME],
        )
        await timer.async_cancel()
        _LOGGER.debug("Finish boost step complete for %s: timer cancelled", entry_id)

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
            _LOGGER.debug(
                "Finish boost step complete for %s: time selector reset to 0 "
                "(entity_id=%s)",
                entry_id,
                time_selector_entity_id,
            )

        boost_active_entity_id = _get_entity_id(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE)
        if boost_active_entity_id:
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": boost_active_entity_id},
                blocking=True,
            )
            _LOGGER.debug(
                "Finish boost step complete for %s: boost marked inactive "
                "(entity_id=%s)",
                entry_id,
                boost_active_entity_id,
            )

        thermostat_name = data[DATA_THERMOSTAT_NAME]
        schedule_override_active = _is_switch_on(
            hass, entry_id, UNIQUE_ID_SCHEDULE_OVERRIDE
        )
        scheduler_switches = get_scheduler_switches_for_thermostat(hass, thermostat_name)
        no_schedules_detected = not scheduler_switches
        has_scheduler_snapshot = await _has_scheduler_snapshot(hass, entry_id)
        _LOGGER.debug(
            "Finish boost restore decision for %s: schedule_override_active=%s, "
            "no_schedules_detected=%s, has_scheduler_snapshot=%s",
            entry_id,
            schedule_override_active,
            no_schedules_detected,
            has_scheduler_snapshot,
        )

        # Prefer scheduler restoration whenever a scheduler snapshot exists.
        if schedule_override_active or not has_scheduler_snapshot:
            _LOGGER.debug(
                "Finish boost for %s selecting target-temperature restore path",
                entry_id,
            )
            restored = await async_restore_target_temperature_snapshot(
                hass,
                entry_id,
                data[CONF_THERMOSTAT],
            )
            if not restored:
                _LOGGER.debug(
                    "Finish boost target-temperature restore for %s did not apply a snapshot "
                    "(override_active=%s, has_scheduler_snapshot=%s)",
                    entry_id,
                    schedule_override_active,
                    has_scheduler_snapshot,
                )
            else:
                _LOGGER.debug(
                    "Finish boost target-temperature restore applied for %s",
                    entry_id,
                )
            return

        _LOGGER.debug(
            "Finish boost for %s selecting scheduler restore path "
            "(expired_while_offline=%s)",
            entry_id,
            expired_while_offline,
        )
        pre_restore_temp_applied = bool(
            await async_restore_target_temperature_snapshot(
                hass,
                entry_id,
                data[CONF_THERMOSTAT],
            )
        )
        _LOGGER.debug(
            "Finish boost for %s pre-restore temperature step: "
            "stored_temperature_applied=%s",
            entry_id,
            pre_restore_temp_applied,
        )
        await async_restore_scheduler_snapshot(
            hass, entry_id, expired_while_offline=expired_while_offline
        )
        _LOGGER.debug(
            "Finish boost for %s invoked scheduler restore "
            "(completion may be deferred/retried; expired_while_offline=%s)",
            entry_id,
            expired_while_offline,
        )
    finally:
        finish_in_progress.discard(entry_id)


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
