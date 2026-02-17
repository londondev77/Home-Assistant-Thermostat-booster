"""Shared scheduler matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util


@dataclass
class SchedulerNowStatus:
    """Current effective scheduler status for a thermostat."""

    active_enabled_entities: list[str]
    active_disabled_entities: list[str]

    @property
    def has_active_enabled_schedule(self) -> bool:
        """Return True when at least one currently-applicable schedule is enabled."""
        return bool(self.active_enabled_entities)


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_time(value: object) -> time | None:
    if not isinstance(value, str) or not value:
        return None
    # Scheduler may support sun events (e.g. sunrise+01:00); skip these here.
    lowered = value.lower()
    if "sunrise" in lowered or "sunset" in lowered:
        return None
    return dt_util.parse_time(value)


def _is_workday(dt_local: datetime) -> bool:
    return dt_local.weekday() < 5


def _weekday_token_matches(token: str, dt_local: datetime) -> bool:
    token_norm = token.strip().lower()
    weekday = dt_local.weekday()
    mapping = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tues": 1,
        "tuesday": 1,
        "wed": 2,
        "weds": 2,
        "wednesday": 2,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }
    if token_norm in ("daily", "everyday", "all"):
        return True
    if token_norm in ("workday", "workdays", "weekday", "weekdays"):
        return _is_workday(dt_local)
    if token_norm in ("weekend", "weekends"):
        return not _is_workday(dt_local)
    day = mapping.get(token_norm)
    return day is not None and day == weekday


def _weekday_matches(weekdays: object, dt_local: datetime) -> bool:
    if weekdays is None:
        return True
    if isinstance(weekdays, str):
        return _weekday_token_matches(weekdays, dt_local)
    if isinstance(weekdays, list):
        return any(
            isinstance(token, str) and _weekday_token_matches(token, dt_local)
            for token in weekdays
        )
    return True


def _date_window_matches(attrs: dict, dt_local: datetime) -> bool:
    today = dt_local.date()
    start_date = _parse_date(attrs.get("start_date"))
    end_date = _parse_date(attrs.get("end_date"))
    if start_date is not None and today < start_date:
        return False
    if end_date is not None and today > end_date:
        return False
    return True


def _time_slot_matches(slot: dict, now_time: time) -> bool:
    start = _parse_time(slot.get("start"))
    if start is None:
        return False
    stop = _parse_time(slot.get("stop"))

    if stop is None:
        # Point-in-time slot (no stop) only matches the exact minute.
        return now_time.hour == start.hour and now_time.minute == start.minute
    if start <= stop:
        return start <= now_time < stop
    # Overnight slot, e.g. 22:00 -> 06:00
    return now_time >= start or now_time < stop


def _schedule_applies_now(attrs: dict, dt_local: datetime) -> bool:
    if not _date_window_matches(attrs, dt_local):
        return False
    if not _weekday_matches(attrs.get("weekdays"), dt_local):
        return False

    now_time = dt_local.time()
    timeslots = attrs.get("timeslots")
    if isinstance(timeslots, list) and timeslots:
        return any(
            isinstance(slot, dict) and _time_slot_matches(slot, now_time)
            for slot in timeslots
        )

    # Fallback for alternate attribute shape.
    fallback_slot = {
        "start": attrs.get("start"),
        "stop": attrs.get("stop") or attrs.get("end"),
    }
    return _time_slot_matches(fallback_slot, now_time)


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


@callback
def get_scheduler_activity_for_thermostat_now(
    hass: HomeAssistant,
    thermostat_name: str,
) -> SchedulerNowStatus:
    """Return which matching schedules apply now and are enabled/disabled."""
    dt_local = dt_util.as_local(dt_util.utcnow())
    active_enabled: list[str] = []
    active_disabled: list[str] = []

    for entity_id in get_scheduler_switches_for_thermostat(hass, thermostat_name):
        state = hass.states.get(entity_id)
        if state is None:
            continue
        if not _schedule_applies_now(state.attributes, dt_local):
            continue
        if state.state == "on":
            active_enabled.append(entity_id)
        else:
            active_disabled.append(entity_id)

    return SchedulerNowStatus(
        active_enabled_entities=active_enabled,
        active_disabled_entities=active_disabled,
    )

