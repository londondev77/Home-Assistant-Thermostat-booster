"""Binary sensor platform for Thermostat Boost."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_ENTRY_TYPE,
    CONF_THERMOSTAT,
    DOMAIN,
    ENTRY_TYPE_AGGREGATE,
    UNIQUE_ID_BOOST_ACTIVE,
    UNIQUE_ID_CALL_FOR_HEAT_ENABLED,
)
from .entity_base import ThermostatBoostEntity

_AGGREGATE_ENTITY_KEY = "call_for_heat_aggregate_entity"
_BOOST_ACTIVE_ENTITY_KEY = "boost_active_binary_entities"
_BOOST_ACTIVE_STATE_KEY = "boost_active_binary_state"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities for Thermostat Boost."""
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_AGGREGATE:
        data = hass.data[DOMAIN][entry.entry_id]
        async_add_entities([BoostActiveBinarySensor(hass, entry, data)])
        return

    domain_data = hass.data.setdefault(DOMAIN, {})
    aggregate = domain_data.get(_AGGREGATE_ENTITY_KEY)
    if aggregate is None:
        aggregate = ThermostatBoostCallForHeatBinarySensor(hass)
        domain_data[_AGGREGATE_ENTITY_KEY] = aggregate
        async_add_entities([aggregate])
        return

    aggregate.async_refresh_tracked_entities()


@callback
def async_set_boost_active_state(
    hass: HomeAssistant, entry_id: str, is_active: bool
) -> None:
    """Set Boost Active binary sensor state for a thermostat entry."""
    _get_boost_active_state_store(hass)[entry_id] = is_active
    entity = _get_boost_active_entities(hass).get(entry_id)
    if entity is not None:
        entity.async_set_active(is_active)


class BoostActiveBinarySensor(ThermostatBoostEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor indicating whether a boost session is active."""

    _attr_icon = "mdi:rocket-launch"
    _attr_entity_registry_visible_default = True

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data: dict
    ) -> None:
        super().__init__(
            hass,
            entry,
            data,
            entity_name="Boost Active",
            unique_id_suffix=UNIQUE_ID_BOOST_ACTIVE,
        )
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore and register sensor instance."""
        await super().async_added_to_hass()
        state_store = _get_boost_active_state_store(self.hass)
        if self._entry.entry_id in state_store:
            self._is_on = bool(state_store[self._entry.entry_id])
        elif (state := await self.async_get_last_state()) is not None:
            self._is_on = state.state == STATE_ON
            state_store[self._entry.entry_id] = self._is_on
        else:
            state_store[self._entry.entry_id] = self._is_on
        _get_boost_active_entities(self.hass)[self._entry.entry_id] = self
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister sensor instance."""
        _get_boost_active_entities(self.hass).pop(self._entry.entry_id, None)

    @property
    def is_on(self) -> bool:
        """Return true if boost is active."""
        return bool(
            _get_boost_active_state_store(self.hass).get(
                self._entry.entry_id, self._is_on
            )
        )

    @callback
    def async_set_active(self, is_active: bool) -> None:
        """Update active state and publish it."""
        self._is_on = bool(is_active)
        self.async_write_ha_state()


class ThermostatBoostCallForHeatBinarySensor(BinarySensorEntity):
    """Aggregate call-for-heat signal across enabled thermostats."""

    _attr_name = "Call for Heat active"
    _attr_unique_id = f"{DOMAIN}_call_for_heat_active"
    _attr_icon = "mdi:broadcast"
    _attr_has_entity_name = False
    _attr_device_info = {
        "identifiers": {(DOMAIN, "call_for_heat_aggregate")},
        "name": "Thermostat Boost Call for Heat",
        "manufacturer": "Thermostat Boost",
        "model": "Aggregate",
    }

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._tracked_entity_ids: set[str] = set()
        self._remove_state_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Register listeners once the entity is added."""
        self.async_refresh_tracked_entities()

    async def async_will_remove_from_hass(self) -> None:
        """Tear down state listeners."""
        if self._remove_state_listener is not None:
            self._remove_state_listener()
            self._remove_state_listener = None

    @property
    def is_on(self) -> bool:
        """Return true when at least one enabled thermostat is actively heating."""
        for entry_id, entry_data in _iter_entry_data(self.hass):
            if not _is_switch_on(
                self.hass, entry_id, UNIQUE_ID_CALL_FOR_HEAT_ENABLED
            ):
                continue

            climate_state = self.hass.states.get(entry_data[CONF_THERMOSTAT])
            hvac_action = climate_state.attributes.get("hvac_action") if climate_state else None
            if isinstance(hvac_action, str) and hvac_action.lower() == "heating":
                return True

        return False

    @callback
    def async_refresh_tracked_entities(self) -> None:
        """Refresh tracked entities for state-change subscriptions."""
        next_ids: set[str] = set()
        for entry_id, entry_data in _iter_entry_data(self.hass):
            next_ids.add(entry_data[CONF_THERMOSTAT])
            if (switch_entity_id := _get_entity_id(
                self.hass, entry_id, UNIQUE_ID_CALL_FOR_HEAT_ENABLED
            )) is not None:
                next_ids.add(switch_entity_id)

        if next_ids != self._tracked_entity_ids:
            self._tracked_entity_ids = next_ids
            if self._remove_state_listener is not None:
                self._remove_state_listener()
                self._remove_state_listener = None
            if next_ids:
                self._remove_state_listener = async_track_state_change_event(
                    self.hass,
                    list(next_ids),
                    self._handle_tracked_state_change,
                )

        if self.entity_id is not None:
            self.async_write_ha_state()

    @callback
    def _handle_tracked_state_change(self, _event) -> None:
        self.async_write_ha_state()


@callback
def _iter_entry_data(hass: HomeAssistant):
    for key, value in hass.data.get(DOMAIN, {}).items():
        if isinstance(value, dict) and CONF_THERMOSTAT in value:
            yield key, value


@callback
def _get_boost_active_entities(
    hass: HomeAssistant,
) -> dict[str, BoostActiveBinarySensor]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_BOOST_ACTIVE_ENTITY_KEY, {})


@callback
def _get_boost_active_state_store(hass: HomeAssistant) -> dict[str, bool]:
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(_BOOST_ACTIVE_STATE_KEY, {})


@callback
def _get_entity_id(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> str | None:
    entity_reg = er.async_get(hass)
    unique_id = f"{entry_id}_{unique_id_suffix}"
    for entry in entity_reg.entities.values():
        if entry.unique_id == unique_id:
            return entry.entity_id
    return None


@callback
def _is_switch_on(hass: HomeAssistant, entry_id: str, unique_id_suffix: str) -> bool:
    entity_id = _get_entity_id(hass, entry_id, unique_id_suffix)
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    return state is not None and state.state == STATE_ON
