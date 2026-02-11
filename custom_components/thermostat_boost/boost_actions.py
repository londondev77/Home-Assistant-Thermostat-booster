"""Shared boost actions."""

from __future__ import annotations

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_THERMOSTAT,
    DATA_THERMOSTAT_NAME,
    DOMAIN,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_TIME_SELECTOR,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.util import slugify


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


def _scene_entity_id(entry_id: str) -> str:
    return f"scene.{slugify(f'thermostat_boost_{entry_id}')}"


async def async_create_scheduler_scene(
    hass: HomeAssistant, entry_id: str, thermostat_name: str
) -> list[str]:
    """Create a scene snapshot for scheduler switches and return the entity_ids."""
    scheduler_switches = _get_scheduler_switches(hass, thermostat_name)
    if not scheduler_switches:
        return []

    await hass.services.async_call(
        "scene",
        "create",
        {
            "scene_id": slugify(f"thermostat_boost_{entry_id}"),
            "snapshot_entities": scheduler_switches,
        },
        blocking=True,
    )
    return scheduler_switches
from .timer_manager import async_get_timer_registry


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

    target_temp = 15.0
    if hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
        target_temp = TemperatureConverter.convert(
            15.0,
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

    boost_active_entity_id = _get_entity_id(hass, entry_id, UNIQUE_ID_BOOST_ACTIVE)
    if boost_active_entity_id:
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": boost_active_entity_id},
            blocking=True,
        )

    scene_entity_id = _scene_entity_id(entry_id)
    if hass.states.get(scene_entity_id) is not None:
        await hass.services.async_call(
            "scene",
            "turn_on",
            {"entity_id": scene_entity_id},
            blocking=True,
        )
