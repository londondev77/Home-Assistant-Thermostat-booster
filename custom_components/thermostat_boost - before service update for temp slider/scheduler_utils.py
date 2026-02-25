"""Shared scheduler matching helpers."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er


def _matches_tag(tags, thermostat_name_lower: str) -> bool:
    if tags is None:
        return False
    if isinstance(tags, str):
        return thermostat_name_lower in tags.lower()
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and thermostat_name_lower in tag.lower():
                return True
    return False


@callback
def get_scheduler_switches_for_thermostat(
    hass: HomeAssistant, thermostat_name: str
) -> list[str]:
    """Return available scheduler switch entity_ids matching thermostat tags."""
    entity_reg = er.async_get(hass)
    thermostat_name_lower = thermostat_name.lower()
    matched: list[str] = []

    for entry in entity_reg.entities.values():
        if entry.domain != "switch" or (entry.platform or "").lower() != "scheduler":
            continue

        state = hass.states.get(entry.entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            continue

        if _matches_tag(state.attributes.get("tags"), thermostat_name_lower):
            matched.append(entry.entity_id)

    return matched

