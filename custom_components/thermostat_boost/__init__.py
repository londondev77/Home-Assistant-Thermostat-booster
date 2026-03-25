"""Thermostat Boost integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
import voluptuous as vol
from .boost_actions import (
    async_clear_scheduler_snapshot,
    async_clear_target_temperature_snapshot,
    async_finish_boost_for_entry,
    async_unregister_external_temperature_monitor,
)
from .frontend import JSModuleRegistration
from .const import (
    CONF_CALL_FOR_HEAT_ENABLED,
    CONF_ENTRY_TYPE,
    CONF_THERMOSTAT,
    CONF_TRACK_ON_DEVICE_CHANGES,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    ENTRY_TYPE_AGGREGATE,
    ENTRY_TYPE_THERMOSTAT,
    EVENT_TIMER_FINISHED,
    SERVICE_FINISH_BOOST,
    SERVICE_START_BOOST,
)
from .entity_base import get_thermostat_name
from .timer_manager import async_get_timer_registry

THERMOSTAT_PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

AGGREGATE_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
]

_AGGREGATE_DEVICE_IDENTIFIER = "call_for_heat_aggregate"
_DELETE_CALL_FOR_HEAT_BLOCKED_MESSAGE = (
    "You are not able to delete Call for Heat manually. "
    "It will be automatically deleted if you remove all thermostats added to "
    "Thermostat Boost."
)

_PICKER_STORAGE_VERSION = 1
_PICKER_STORAGE_KEY = f"{DOMAIN}.picker_selection"
_PICKER_WS_GET = f"{DOMAIN}/picker/get_selection"
_PICKER_WS_SET = f"{DOMAIN}/picker/set_selection"
_PICKER_WS_REGISTERED = "picker_ws_registered"


def _get_picker_store(hass: HomeAssistant) -> Store:
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = domain_data.get("picker_store")
    if store is None:
        store = Store(hass, _PICKER_STORAGE_VERSION, _PICKER_STORAGE_KEY)
        domain_data["picker_store"] = store
    return store


async def _async_get_picker_data(hass: HomeAssistant) -> dict:
    domain_data = hass.data.setdefault(DOMAIN, {})
    data = domain_data.get("picker_data")
    if data is None:
        store = _get_picker_store(hass)
        data = await store.async_load() or {}
        domain_data["picker_data"] = data
    return data


async def _async_save_picker_data(hass: HomeAssistant, data: dict) -> None:
    store = _get_picker_store(hass)
    await store.async_save(data)
    hass.data.setdefault(DOMAIN, {})["picker_data"] = data


def _async_register_picker_ws(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_PICKER_WS_REGISTERED):
        return
    websocket_api.async_register_command(hass, _ws_get_picker_selection)
    websocket_api.async_register_command(hass, _ws_set_picker_selection)
    domain_data[_PICKER_WS_REGISTERED] = True


@websocket_api.websocket_command(
    {
        vol.Required("type"): _PICKER_WS_GET,
        vol.Optional("user_id"): str,
    }
)
@websocket_api.async_response
async def _ws_get_picker_selection(hass: HomeAssistant, connection, msg) -> None:
    user_id = msg.get("user_id")
    if not user_id and connection.user:
        user_id = connection.user.id
    if not user_id:
        connection.send_error(msg["id"], "no_user", "User not available")
        return

    data = await _async_get_picker_data(hass)
    users = data.get("users")
    selection = {}
    if isinstance(users, dict):
        entry = users.get(user_id)
        if isinstance(entry, dict):
            selection = entry.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {}

    connection.send_result(msg["id"], {"selection": selection})


@websocket_api.websocket_command(
    {
        vol.Required("type"): _PICKER_WS_SET,
        vol.Optional("user_id"): str,
        vol.Required("selection"): dict,
    }
)
@websocket_api.async_response
async def _ws_set_picker_selection(hass: HomeAssistant, connection, msg) -> None:
    user_id = msg.get("user_id")
    if not user_id and connection.user:
        user_id = connection.user.id
    if not user_id:
        connection.send_error(msg["id"], "no_user", "User not available")
        return

    selection_in = msg.get("selection") or {}
    cleaned = {}
    if isinstance(selection_in, dict):
        for key, value in selection_in.items():
            if not isinstance(key, str):
                continue
            cleaned[key] = bool(value)

    data = await _async_get_picker_data(hass)
    users = data.get("users")
    if not isinstance(users, dict):
        users = {}
        data["users"] = users
    users[user_id] = {"selection": cleaned}
    await _async_save_picker_data(hass, data)

    connection.send_result(msg["id"], {"ok": True})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Thermostat Boost from a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
    hass.data.setdefault(DOMAIN, {})
    await JSModuleRegistration(hass).async_register()
    _async_register_picker_ws(hass)
    _cleanup_legacy_aggregate_entity_binding(hass)

    if entry_type == ENTRY_TYPE_AGGREGATE:
        hass.data[DOMAIN][entry.entry_id] = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_AGGREGATE,
        }
        await hass.config_entries.async_forward_entry_setups(
            entry, AGGREGATE_PLATFORMS
        )
        return True

    thermostat_entity_id = entry.data[CONF_THERMOSTAT]
    thermostat_name = get_thermostat_name(hass, thermostat_entity_id)

    if "finish_listener" not in hass.data[DOMAIN]:
        def _handle_timer_finished_event(event) -> None:
            hass.add_job(_handle_timer_finished(hass, event))

        hass.data[DOMAIN]["finish_listener"] = hass.bus.async_listen(
            EVENT_TIMER_FINISHED,
            _handle_timer_finished_event,
        )
    if "finish_callback" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["finish_callback"] = async_finish_boost_for_entry
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_THERMOSTAT,
        CONF_THERMOSTAT: thermostat_entity_id,
        CONF_CALL_FOR_HEAT_ENABLED: bool(
            entry.data.get(CONF_CALL_FOR_HEAT_ENABLED, False)
        ),
        CONF_TRACK_ON_DEVICE_CHANGES: bool(
            entry.data.get(CONF_TRACK_ON_DEVICE_CHANGES, False)
        ),
        DATA_THERMOSTAT_NAME: thermostat_name,
    }

    # Clean up legacy boost timer entity if it exists.
    entity_reg = er.async_get(hass)
    legacy_unique_id = f"{entry.entry_id}_boost_timer"
    for entity_entry in list(entity_reg.entities.values()):
        if entity_entry.unique_id == legacy_unique_id:
            entity_reg.async_remove(entity_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, THERMOSTAT_PLATFORMS)
    await _async_ensure_aggregate_entry(hass)
    aggregate = hass.data.get(DOMAIN, {}).get("call_for_heat_aggregate_entity")
    if aggregate is not None:
        aggregate.async_refresh_tracked_entities()
    return True


async def _handle_timer_finished(hass: HomeAssistant, event) -> None:
    """Handle timer finish event by calling finish_boost service."""
    entry_id = event.data.get("entry_id")
    if not entry_id:
        return

    expired_while_offline = bool(event.data.get("expired_while_offline"))
    await async_finish_boost_for_entry(
        hass,
        entry_id,
        expired_while_offline=expired_while_offline,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Thermostat Boost config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
    platforms = (
        AGGREGATE_PLATFORMS
        if entry_type == ENTRY_TYPE_AGGREGATE
        else THERMOSTAT_PLATFORMS
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        if entry_type == ENTRY_TYPE_THERMOSTAT:
            registry = await async_get_timer_registry(hass)
            await registry.async_unload_entry(entry.entry_id)
            async_unregister_external_temperature_monitor(hass, entry.entry_id)
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
            if not _get_thermostat_entries(hass, exclude_entry_id=entry.entry_id):
                _cleanup_domain_shared_state(hass)
                await JSModuleRegistration(hass).async_unregister()
            aggregate = hass.data.get(DOMAIN, {}).get("call_for_heat_aggregate_entity")
            if aggregate is not None:
                aggregate.async_refresh_tracked_entities()
        else:
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
            hass.data.get(DOMAIN, {}).pop("call_for_heat_aggregate_entity", None)
            if _get_thermostat_entries(hass):
                await _async_notify_call_for_heat_delete_blocked(hass)
                await _async_ensure_aggregate_entry(hass)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a Thermostat Boost config entry and clear persisted state."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
    if entry_type == ENTRY_TYPE_AGGREGATE:
        if _get_thermostat_entries(hass):
            await _async_notify_call_for_heat_delete_blocked(hass)
            await _async_ensure_aggregate_entry(hass)
        else:
            await JSModuleRegistration(hass).async_unregister()
        return

    registry = await async_get_timer_registry(hass)
    await registry.async_remove(entry.entry_id)
    async_unregister_external_temperature_monitor(hass, entry.entry_id)
    await async_clear_scheduler_snapshot(hass, entry.entry_id)
    await async_clear_target_temperature_snapshot(hass, entry.entry_id)
    if not _get_thermostat_entries(hass, exclude_entry_id=entry.entry_id):
        _cleanup_domain_shared_state(hass)
        await JSModuleRegistration(hass).async_unregister()
        await _async_remove_aggregate_entries(hass)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry | str,
) -> bool:
    """Block manual deletion of the aggregate Call for Heat device."""
    del config_entry
    if isinstance(device_entry, str):
        device_registry = dr.async_get(hass)
        resolved_device_entry = device_registry.async_get(device_entry)
        if resolved_device_entry is None:
            return True
        device_entry = resolved_device_entry

    if not _is_call_for_heat_aggregate_device(hass, device_entry):
        return True

    # Preserve expected behavior: once all thermostat entries are gone, aggregate
    # removal is allowed.
    if not _get_thermostat_entries(hass):
        return True

    await _async_notify_call_for_heat_delete_blocked(hass)
    return False


def _get_thermostat_entries(
    hass: HomeAssistant, *, exclude_entry_id: str | None = None
) -> list[ConfigEntry]:
    return [
        domain_entry
        for domain_entry in hass.config_entries.async_entries(DOMAIN)
        if domain_entry.entry_id != exclude_entry_id
        and domain_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
        == ENTRY_TYPE_THERMOSTAT
    ]


def _get_aggregate_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        domain_entry
        for domain_entry in hass.config_entries.async_entries(DOMAIN)
        if domain_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_AGGREGATE
    ]


async def _async_ensure_aggregate_entry(hass: HomeAssistant) -> None:
    if _get_aggregate_entries(hass):
        return

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("aggregate_entry_creating"):
        return

    domain_data["aggregate_entry_creating"] = True
    try:
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "aggregate_auto"},
            data={},
        )
    finally:
        domain_data["aggregate_entry_creating"] = False


async def _async_remove_aggregate_entries(hass: HomeAssistant) -> None:
    for aggregate_entry in _get_aggregate_entries(hass):
        await hass.config_entries.async_remove(aggregate_entry.entry_id)


async def _async_notify_call_for_heat_delete_blocked(hass: HomeAssistant) -> None:
    """Show a stable message when manual aggregate deletion is blocked/reverted."""
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Thermostat Boost",
            "message": _DELETE_CALL_FOR_HEAT_BLOCKED_MESSAGE,
            "notification_id": f"{DOMAIN}_call_for_heat_delete_blocked",
        },
        blocking=True,
    )


def _cleanup_domain_shared_state(hass: HomeAssistant) -> None:
    """Tear down domain-level listeners/services once no thermostats remain."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if (finish_listener_unsub := domain_data.pop("finish_listener", None)) is not None:
        finish_listener_unsub()

    domain_data.pop("finish_callback", None)

    if hass.services.has_service(DOMAIN, SERVICE_START_BOOST):
        hass.services.async_remove(DOMAIN, SERVICE_START_BOOST)
    if hass.services.has_service(DOMAIN, SERVICE_FINISH_BOOST):
        hass.services.async_remove(DOMAIN, SERVICE_FINISH_BOOST)


def _cleanup_legacy_aggregate_entity_binding(hass: HomeAssistant) -> None:
    """Remove aggregate entity rows incorrectly bound to thermostat entries."""
    entity_reg = er.async_get(hass)
    aggregate_unique_ids = {
        f"{DOMAIN}_call_for_heat",
        f"{DOMAIN}_call_for_heat_active",
    }
    entries_by_id = {entry.entry_id: entry for entry in hass.config_entries.async_entries(DOMAIN)}
    expected_name = "Call for Heat active"

    for entity_entry in list(entity_reg.entities.values()):
        if entity_entry.unique_id not in aggregate_unique_ids:
            continue

        # Remove legacy aggregate unique_id unconditionally.
        if entity_entry.unique_id == f"{DOMAIN}_call_for_heat":
            entity_reg.async_remove(entity_entry.entity_id)
            continue

        config_entry = entries_by_id.get(entity_entry.config_entry_id)
        bound_to_thermostat = (
            config_entry is not None
            and config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
            == ENTRY_TYPE_THERMOSTAT
        )
        has_stale_name = entity_entry.original_name != expected_name

        if bound_to_thermostat or has_stale_name:
            entity_reg.async_remove(entity_entry.entity_id)


def _is_call_for_heat_aggregate_device(
    hass: HomeAssistant, device_entry: dr.DeviceEntry
) -> bool:
    if any(
        domain == DOMAIN and identifier == _AGGREGATE_DEVICE_IDENTIFIER
        for domain, identifier in device_entry.identifiers
    ):
        return True

    if (
        device_entry.manufacturer == "Thermostat Boost"
        and device_entry.model == "Aggregate"
    ):
        return True

    entity_reg = er.async_get(hass)
    aggregate_unique_ids = {
        f"{DOMAIN}_call_for_heat_active",
        f"{DOMAIN}_call_for_heat",
    }
    for entity_entry in er.async_entries_for_device(
        entity_reg, device_entry.id, include_disabled_entities=True
    ):
        if entity_entry.unique_id in aggregate_unique_ids:
            return True

    return False
