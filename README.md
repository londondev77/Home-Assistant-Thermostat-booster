# Thermostat Boost (Home Assistant)

Thermostat Boost is a custom Home Assistant integration that temporarily raises a thermostat setpoint for a fixed duration, then automatically returns control to your normal scheduling.

It is designed for homes that already use schedules and need a reliable, temporary "boost" without manually editing schedule blocks.

## Benefits

- Fast temporary heat boost without touching your normal schedule setup.
- Automatic return to scheduled control when boost ends.
- Better resilience during Home Assistant restarts or short outages.
- Consistent workflow across multiple thermostats (one integration entry per thermostat).
- Script and automation friendly services (`start_boost`, `finish_boost`, timer controls).

## Features

- Per-thermostat boost entities:
  - `Boost Temperature` number slider
  - `Boost Time Selector` number slider
  - `Boost Active` switch
  - `Boost Finish` sensor
- `start_boost` service to:
  - set thermostat target temperature
  - start boost timer
  - mark boost active
  - snapshot and disable matching Scheduler switches while boost is active
- `finish_boost` service to:
  - cancel timer
  - mark boost inactive
  - reset time selector to `0`
  - restore Scheduler switches to their pre-boost on/off states
  - or restore the original thermostat target temperature when Schedule Override is active or no schedules are matched
- Timer persistence across reboot:
  - timer end timestamps are stored
  - active timers are reconstructed after restart
  - if a timer expired while HA was offline, finish logic is triggered on startup
- State restoration for boost entities via `RestoreEntity`.
- Supports multiple thermostats by adding multiple config entries.

## Reliability Mitigations

The integration includes several safeguards specifically to handle restarts and edge cases:

- Persistent timer state:
  - Timer end times are saved to storage and reloaded after restart.
  - Expired-during-offline boosts are finished immediately when HA comes back.

- Persistent scheduler snapshot:
  - Before disabling schedules, current Scheduler switch states are stored.
  - Stored snapshot is used to restore the exact previous on/off states at boost end.

- Retry when entities are unavailable:
  - If scheduler entities are `unknown`/`unavailable` during restore, restore is deferred and retried.
  - If a restore service call fails, restore is retried.

- Double-switch retrigger (important mitigation):
  - After restoring schedules, switches that should be on are toggled `off -> on` again after a short delay.
  - This retrigger helps ensure Scheduler resumes correctly, including cases where boost expiry happened while HA was down.

- Finish callback fallback:
  - A direct callback path exists in addition to the event listener, reducing risk of missed finish handling.

## Installation

1. Add this repository as a custom integration in HACS.
2. Install **Thermostat Boost**.
3. Restart Home Assistant.
4. Go to **Settings -> Devices & Services -> Add Integration**.
5. Select **Thermostat Boost**.
6. Choose the target thermostat from the dropdown.

Repeat steps 4-6 for each thermostat you want to control.

## Dependencies

The integration backend itself has no external Python package requirements in `manifest.json`, but the full feature set depends on these Home Assistant add-ons/custom cards:

| Dependency | Required for | Why it is needed | GitHub |
|---|---|---|---|
| Home Assistant Core | Always | Runs the integration and provides climate/services/entity framework | https://github.com/home-assistant/core |
| Scheduler Component | Recommended (required for schedule pause/restore logic) | Provides `switch` entities on platform `scheduler` that are snapshotted/restored during boost | https://github.com/nielsfaber/scheduler-component |
| Bubble Card | Required if using `www/thermostat-boost-card.js` | The custom card renders with `custom:bubble-card` (header + pop-up views) | https://github.com/Clooos/Bubble-Card |
| Scheduler Card | Required if using `www/thermostat-boost-card.js` | The custom card embeds `custom:scheduler-card` to show/edit thermostat schedules | https://github.com/nielsfaber/scheduler-card |
| Slider Entity Row | Required if using `www/thermostat-boost-card.js` | Boost time/temperature controls use `custom:slider-entity-row` | https://github.com/thomasloven/lovelace-slider-entity-row |

Notes:

- `scheduler-card` is designed to work with `scheduler-component`; if you use the card, install both.
- If you do not use `www/thermostat-boost-card.js`, Bubble Card / Scheduler Card / Slider Entity Row are not required for backend services to run.

## Scheduler Integration Notes

For schedule pause/restore to work, Scheduler switches must be discoverable and associated with the thermostat.

Current matching logic:

- Looks for entities in domain `switch` from platform `scheduler`.
- Uses Scheduler switch `tags` and matches the thermostat name (case-insensitive substring).

Recommended:

- Keep thermostat friendly names stable.
- Include thermostat-identifying tags on related Scheduler entries.

If no matching Scheduler switches are found, boost temperature is still set and timer still runs, but schedule pause/restore behavior will not apply.

## Schedule Override (Long-Term Changes)

For longer-term changes (for example holidays), use Scheduler/Scheduler Card to create or enable an override schedule for the thermostat.

- Boost is intentionally short-lived and timer-based, so it will auto-finish.
- A scheduler override can stay in place across days/weeks and does not have to auto-revert on a boost timer.
- When you are ready to return to normal operation, disable/remove the override schedule in Scheduler.

This gives you two control patterns:

1. `start_boost` for temporary heat increases that should end automatically.
2. Scheduler override rules for extended periods where you want manual control of when it ends.

## Entities Created

For each thermostat entry:

- `sensor.<thermostat>_boost_finish`
- `switch.<thermostat>_boost_active`
- `number.<thermostat>_boost_temperature`
- `number.<thermostat>_boost_time_selector`

(Exact entity IDs depend on your naming/entity registry.)

## Services

### `thermostat_boost.start_boost`

Starts a full boost session.

Inputs:

- `device_id` (required)
- `time` (optional duration selector object or `HH:MM:SS`)
- `temperature_c` (optional, defaults to Boost Temperature slider)

Example:

```yaml
service: thermostat_boost.start_boost
data:
  device_id: 1234567890abcdef1234567890abcdef
  time:
    hours: 1
    minutes: 30
  temperature_c: 21.0
```

### `thermostat_boost.finish_boost`

Ends boost and restores scheduler state.

Example:

```yaml
service: thermostat_boost.finish_boost
target:
  entity_id: sensor.lounge_boost_finish
```

## Typical Boost Flow

1. Call `start_boost`.
2. Thermostat setpoint is raised.
3. Matching scheduler switches are snapshotted and turned off.
4. Boost runs until timer expires (or until manual finish).
5. On finish, scheduler snapshot is restored.
6. Scheduler on-switches are retriggered (`off -> on`) as a resilience step.

## Optional Lovelace Card

This repository includes `www/thermostat-boost-card.js`, a custom Lovelace card for:

- boost time/temperature controls
- start/cancel actions
- countdown display

If you use it, add the JS resource in Dashboard resources and configure the card with the relevant Thermostat Boost device.

## Known Behavior

- When Schedule Override is active, or no matching Scheduler switches are found for the thermostat, boost stores and restores the original thermostat target temperature.
- Otherwise, boost end restores Scheduler switch state and retriggers schedule switches that were previously on.
- For best results, use this integration with Scheduler rules that define your normal temperature behavior.

## Development Status

Current integration version in `manifest.json`: `0.1.0`.

