"""Shared scheduler matching helpers."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er


def _matches_thermostat_entity(entities, thermostat_entity_id: str) -> bool:
    """Return True when scheduler entities include the thermostat entity_id."""
    if entities is None:
        return False
    if isinstance(entities, str):
        return entities == thermostat_entity_id
    if isinstance(entities, list):
        for entity_id in entities:
            if isinstance(entity_id, str) and entity_id == thermostat_entity_id:
                return True
    return False


@callback
def get_scheduler_switches_for_thermostat(
    hass: HomeAssistant, thermostat_entity_id: str
) -> list[str]:
    """Return available scheduler switch entity_ids matching thermostat entity."""
    entity_reg = er.async_get(hass)
    matched: list[str] = []

    for entry in entity_reg.entities.values():
        if entry.domain != "switch" or (entry.platform or "").lower() != "scheduler":
            continue

        state = hass.states.get(entry.entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            continue

        if _matches_thermostat_entity(
            state.attributes.get("entities"), thermostat_entity_id
        ):
            matched.append(entry.entity_id)

    return matched

