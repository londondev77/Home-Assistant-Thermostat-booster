"""Shared entity helpers for Thermostat Boost."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import CONF_THERMOSTAT, DATA_THERMOSTAT_NAME, DOMAIN


def get_thermostat_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return a friendly name for the thermostat."""
    state = hass.states.get(entity_id)
    if state is not None:
        friendly = state.attributes.get("friendly_name")
        if friendly:
            return str(friendly)

    # Fallback: derive from entity id.
    if "." in entity_id:
        object_id = entity_id.split(".", 1)[1]
        return object_id.replace("_", " ").title()
    return entity_id


class ThermostatBoostEntity(Entity):
    """Base class for Thermostat Boost entities."""

    _attr_has_entity_name = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        data: dict,
        entity_name: str,
        unique_id_suffix: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._data = data

        thermostat_name = data[DATA_THERMOSTAT_NAME]
        thermostat_entity_id = data[CONF_THERMOSTAT]

        self._attr_name = f"{thermostat_name} {entity_name}"
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, thermostat_entity_id)},
            "name": thermostat_name,
            "manufacturer": "Thermostat Boost",
            "model": "Thermostat",
        }
