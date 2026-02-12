"""Timer state management and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT_TIMER_FINISHED

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.timer"


@dataclass
class TimerSnapshot:
    """Snapshot of timer state."""

    remaining: timedelta
    status: str
    end: datetime | None


class BoostTimer:
    """Per-entry timer with persistence."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        thermostat_entity_id: str,
        thermostat_name: str,
        registry: "TimerRegistry",
        end: datetime | None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.thermostat_entity_id = thermostat_entity_id
        self.thermostat_name = thermostat_name
        self._registry = registry
        self._end = end
        self._unsub_point: Callable[[], None] | None = None
        self._callbacks: set[Callable[[], None]] = set()

        if self._end is not None:
            self._schedule_finish()

    @callback
    def add_listener(self, callback_func: Callable[[], None]) -> Callable[[], None]:
        """Add a listener for timer updates."""
        self._callbacks.add(callback_func)

        @callback
        def _remove() -> None:
            self._callbacks.discard(callback_func)

        return _remove

    @callback
    def _notify(self) -> None:
        for callback_func in list(self._callbacks):
            callback_func()

    @callback
    def _cancel_schedule(self) -> None:
        if self._unsub_point is not None:
            self._unsub_point()
            self._unsub_point = None

    @callback
    def _schedule_finish(self) -> None:
        self._cancel_schedule()
        if self._end is None:
            return
        self._unsub_point = async_track_point_in_utc_time(
            self.hass, self._handle_finish, dt_util.as_utc(self._end)
        )

    @callback
    def _handle_finish(self, now: datetime) -> None:
        if self._end is None:
            return
        if now >= self._end:
            self.hass.async_create_task(self.async_finish(expired_while_offline=False))

    def snapshot(self) -> TimerSnapshot:
        """Return a snapshot of the current timer state."""
        now = dt_util.utcnow()
        if self._end is None or self._end <= now:
            return TimerSnapshot(
                remaining=timedelta(0),
                status="idle",
                end=None if self._end is None else self._end,
            )

        return TimerSnapshot(
            remaining=self._end - now,
            status="active",
            end=self._end,
        )

    async def async_start(self, duration: timedelta) -> None:
        """Start the timer for a duration."""
        now = dt_util.utcnow()
        if duration.total_seconds() <= 0:
            await self.async_finish(expired_while_offline=False)
            return

        self._end = now + duration
        await self._registry.async_set_end(self.entry_id, self._end)
        self._schedule_finish()
        self._notify()

    async def async_cancel(self) -> None:
        """Cancel the timer."""
        self._end = None
        await self._registry.async_set_end(self.entry_id, None)
        self._cancel_schedule()
        self._notify()

    async def async_finish(self, *, expired_while_offline: bool) -> None:
        """Finish the timer and fire the event."""
        self._end = None
        await self._registry.async_set_end(self.entry_id, None)
        self._cancel_schedule()
        self._notify()

        self.hass.bus.async_fire(
            EVENT_TIMER_FINISHED,
            {
                "entry_id": self.entry_id,
                "thermostat_entity_id": self.thermostat_entity_id,
                "thermostat_name": self.thermostat_name,
                "expired_while_offline": expired_while_offline,
            },
        )

        # Direct callback fallback in case the event listener isn't registered.
        callback = self.hass.data.get(DOMAIN, {}).get("finish_callback")
        if callable(callback):
            self.hass.async_create_task(callback(self.hass, self.entry_id))

    @callback
    def unload(self) -> None:
        """Unload timer callbacks without clearing persisted state."""
        self._cancel_schedule()
        self._callbacks.clear()


class TimerRegistry:
    """Registry for per-entry timers with persistent storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, float] | None = None
        self._timers: dict[str, BoostTimer] = {}

    async def async_initialize(self) -> None:
        """Load data from storage (once)."""
        if self._data is not None:
            return

        self._data = await self._store.async_load() or {}

    async def async_set_end(self, entry_id: str, end: datetime | None) -> None:
        """Persist a timer end time."""
        await self.async_initialize()
        if self._data is None:
            return

        if end is None:
            self._data.pop(entry_id, None)
        else:
            self._data[entry_id] = dt_util.as_timestamp(end)

        await self._store.async_save(self._data)

    async def async_get_timer(
        self,
        entry_id: str,
        thermostat_entity_id: str,
        thermostat_name: str,
    ) -> BoostTimer:
        """Get or create a timer for a config entry."""
        await self.async_initialize()
        if self._data is None:
            self._data = {}

        if entry_id in self._timers:
            return self._timers[entry_id]

        end = None
        if (end_ts := self._data.get(entry_id)) is not None:
            end = dt_util.utc_from_timestamp(end_ts)

        timer = BoostTimer(
            self.hass,
            entry_id,
            thermostat_entity_id,
            thermostat_name,
            self,
            end=end,
        )

        # Handle timers that expired while HA was offline.
        if end is not None and end <= dt_util.utcnow():
            await timer.async_finish(expired_while_offline=True)
        elif end is not None:
            timer._schedule_finish()

        self._timers[entry_id] = timer
        return timer

    async def async_remove(self, entry_id: str) -> None:
        """Remove a timer and clear persisted state."""
        if entry_id in self._timers:
            await self._timers[entry_id].async_cancel()
            self._timers.pop(entry_id, None)
        await self.async_set_end(entry_id, None)

    async def async_unload_entry(self, entry_id: str) -> None:
        """Unload a timer without clearing persisted state."""
        timer = self._timers.pop(entry_id, None)
        if timer is not None:
            timer.unload()


async def async_get_timer_registry(hass: HomeAssistant) -> TimerRegistry:
    """Get or create the timer registry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "timer_registry" not in domain_data:
        domain_data["timer_registry"] = TimerRegistry(hass)
    return domain_data["timer_registry"]
