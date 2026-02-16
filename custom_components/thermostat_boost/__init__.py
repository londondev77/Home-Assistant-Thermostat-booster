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
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    EVENT_TIMER_FINISHED,
)
from .entity_base import get_thermostat_name
from .timer_manager import async_get_timer_registry

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Thermostat Boost from a config entry."""
    thermostat_entity_id = entry.data[CONF_THERMOSTAT]
    thermostat_name = get_thermostat_name(hass, thermostat_entity_id)

    hass.data.setdefault(DOMAIN, {})
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
        CONF_THERMOSTAT: thermostat_entity_id,
        DATA_THERMOSTAT_NAME: thermostat_name,
    }

    # Clean up legacy boost timer entity if it exists.
    entity_reg = er.async_get(hass)
    legacy_unique_id = f"{entry.entry_id}_boost_timer"
    for entity_entry in list(entity_reg.entities.values()):
        if entity_entry.unique_id == legacy_unique_id:
            entity_reg.async_remove(entity_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
        allow_retrigger=expired_while_offline,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Thermostat Boost config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        registry = await async_get_timer_registry(hass)
        await registry.async_unload_entry(entry.entry_id)
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a Thermostat Boost config entry and clear persisted state."""
    registry = await async_get_timer_registry(hass)
    await registry.async_remove(entry.entry_id)
    await async_clear_scheduler_snapshot(hass, entry.entry_id)
    await async_clear_target_temperature_snapshot(hass, entry.entry_id)
