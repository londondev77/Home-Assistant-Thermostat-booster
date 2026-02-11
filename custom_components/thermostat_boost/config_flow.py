"""Config flow for Thermostat Boost."""

from __future__ import annotations

from typing import Iterable

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import selector

from .const import CONF_THERMOSTAT, DOMAIN


def _climate_entity_ids(hass: HomeAssistant) -> list[str]:
    """Return all climate entity ids, sorted."""
    entity_reg = er.async_get(hass)
    entity_ids: set[str] = {
        entry.entity_id
        for entry in entity_reg.entities.values()
        if entry.domain == "climate"
    }

    # Include any climate entities not in the registry (rare, but possible).
    entity_ids.update(state.entity_id for state in hass.states.async_all("climate"))

    return sorted(entity_ids)


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Return a friendly name for the entity if available."""
    state = hass.states.get(entity_id)
    if state is None:
        return entity_id
    return state.attributes.get("friendly_name", entity_id)


def _available_thermostats(
    hass: HomeAssistant, configured: Iterable[str]
) -> list[dict]:
    """Return available thermostat selector options, sorted."""
    configured_set = set(configured)
    entity_ids = [
        entity_id
        for entity_id in _climate_entity_ids(hass)
        if entity_id not in configured_set
    ]
    options = [
        {"value": entity_id, "label": _friendly_name(hass, entity_id)}
        for entity_id in entity_ids
    ]
    return sorted(options, key=lambda opt: (opt["label"].lower(), opt["value"]))


class ThermostatBoostConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thermostat Boost."""

    VERSION = 1

    @callback
    def _configured_thermostats(self) -> set[str]:
        return {
            entry.data[CONF_THERMOSTAT]
            for entry in self._async_current_entries()
            if CONF_THERMOSTAT in entry.data
        }

    async def async_step_user(self, user_input: dict | None = None):
        """Handle the initial step."""
        if user_input is not None:
            thermostat = user_input[CONF_THERMOSTAT]
            await self.async_set_unique_id(thermostat)
            self._abort_if_unique_id_configured()
            title = _friendly_name(self.hass, thermostat)
            return self.async_create_entry(title=title, data=user_input)

        options = _available_thermostats(self.hass, self._configured_thermostats())
        if not options:
            return self.async_abort(reason="no_thermostats")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_THERMOSTAT): selector(
                    {
                        "select": {
                            "options": options,
                            "mode": "dropdown",
                        }
                    }
                )
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)
