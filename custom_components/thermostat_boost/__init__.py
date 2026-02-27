"""Thermostat Boost integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from .boost_actions import (
    async_clear_scheduler_snapshot,
    async_clear_target_temperature_snapshot,
    async_finish_boost_for_entry,
)
from .const import (
    CONF_CALL_FOR_HEAT_ENABLED,
    CONF_ENTRY_TYPE,
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    ENTRY_TYPE_AGGREGATE,
    ENTRY_TYPE_THERMOSTAT,
    EVENT_TIMER_FINISHED,
)
from .entity_base import get_thermostat_name
from .timer_manager import async_get_timer_registry

THERMOSTAT_PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
]

AGGREGATE_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Thermostat Boost from a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
    hass.data.setdefault(DOMAIN, {})
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
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
            aggregate = hass.data.get(DOMAIN, {}).get("call_for_heat_aggregate_entity")
            if aggregate is not None:
                aggregate.async_refresh_tracked_entities()
        else:
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
            hass.data.get(DOMAIN, {}).pop("call_for_heat_aggregate_entity", None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a Thermostat Boost config entry and clear persisted state."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_THERMOSTAT)
    if entry_type == ENTRY_TYPE_AGGREGATE:
        return

    registry = await async_get_timer_registry(hass)
    await registry.async_remove(entry.entry_id)
    await async_clear_scheduler_snapshot(hass, entry.entry_id)
    await async_clear_target_temperature_snapshot(hass, entry.entry_id)
    if not _get_thermostat_entries(hass, exclude_entry_id=entry.entry_id):
        await _async_remove_aggregate_entries(hass)


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
