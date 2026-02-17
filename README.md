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
  - store pre-boost thermostat target temperature (first start when boost was not already active)
  - snapshot and disable matching Scheduler switches while boost is active
- `finish_boost` service to:
  - cancel timer
  - mark boost inactive
  - reset time selector to `0`
  - restore the pre-boost thermostat target temperature snapshot first (if present)
  - restore Scheduler switches to their pre-boost on/off states
  - run `scheduler.run_action` for schedules restored to ON
  - scheduler actions then determine the effective target temperature when applicable
- Dynamic boost temperature slider bounds:
  - reads thermostat `min_temp` and `max_temp` attributes
  - if `min_temp` is unavailable, defaults to `0`
  - if `max_temp` is unavailable, defaults to `25`
  - if both values are `0`, uses `0-25`
  - if only one value is `0`, that `0` is kept as-is
  - updates dynamically when thermostat min/max attributes change (no integration reload required)
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

- Offline-expiry scheduler action replay:
  - For timers that expired while HA was offline, scheduler restore still uses availability retries before applying states.
  - After ON-state schedules are restored, the integration calls `scheduler.run_action` for each restored ON schedule switch to ensure schedule actions are applied.

- Current implementation note (for future cleanup):
  - Additional retry/retrigger scaffolding is still present in code for tuning/rollback safety.
  - Offline-expiry stabilization wait is currently configured to `0s`.
  - Retrigger queue delay is currently configured to `0s`.
  - Retrigger off->on step delay remains `10s`, but this path is currently inactive.
- The current offline-expiry path does not use the retrigger sequence; `scheduler.run_action` is used instead.

- Start/finish schedule-state decision:
  - Start boost stores a pre-boost thermostat target temperature snapshot (first start only).
  - Finish boost (scheduler path) applies the pre-boost temperature snapshot first (if available).
  - Finish boost then restores scheduler switch states.
  - Finish boost then runs `scheduler.run_action` for schedules restored to ON.
  - If a restored ON schedule has an action applicable "now", scheduler action typically overrides the pre-boost restore.
  - If no restored ON schedule has an applicable action "now", the pre-boost temperature typically remains in effect.

| Schedule Active At Start | Any Restored ON Schedule Applies "Now" At Finish | Temperature Outcome At Finish | Expected Key Log Line(s) |
|---|---|---|---|
| Yes | Yes | Scheduler remains in control; scheduler action usually overrides the pre-boost restore. | `Start boost schedule check ... schedule_active_at_start=True ...`, `Finish boost ... pre-restore temperature step: stored_temperature_applied=True`, and `Scheduler run_action completed ...` |
| Yes | No | Pre-boost temperature typically remains in effect. | `Start boost schedule check ... schedule_active_at_start=True ...` and `Finish boost ... pre-restore temperature step: stored_temperature_applied=True` |
| No | Yes | Scheduler remains in control; scheduler action usually overrides the pre-boost restore. | `Start boost schedule check ... schedule_active_at_start=False ...`, `Finish boost ... pre-restore temperature step: stored_temperature_applied=True`, and `Scheduler run_action completed ...` |
| No | No | Pre-boost temperature typically remains in effect. | `Start boost schedule check ... schedule_active_at_start=False ...` and `Finish boost ... pre-restore temperature step: stored_temperature_applied=True` |

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

## Debug Logging

To see detailed integration logs (including scheduler snapshot/restore/retry decisions), enable debug logging for the integration namespace.

Persistent (`configuration.yaml`):

```yaml
logger:
  logs:
    custom_components.thermostat_boost: debug
```

Temporary (Developer Tools -> Actions -> `logger.set_level`):

```yaml
custom_components.thermostat_boost: debug
```

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
6. If boost is recovered as expired while HA was offline, scheduler snapshot restore includes availability retries and then calls `scheduler.run_action` for restored ON schedules.

## Optional Lovelace Card

This repository includes `www/thermostat-boost-card.js`, a custom Lovelace card for:

- boost time/temperature controls
- start/cancel actions
- countdown display

If you use it, add the JS resource in Dashboard resources and configure the card with the relevant Thermostat Boost device.

## Known Behavior

- Boost stores a pre-boost thermostat target temperature snapshot on first start.
- Boost end always attempts scheduler state restore when a scheduler snapshot exists.
- Boost scheduler-path finish applies pre-boost temperature snapshot first (if present).
- After scheduler restore, `scheduler.run_action` is called for schedules restored to ON.
- Scheduler action may override the pre-boost temperature restore when an applicable schedule action exists.
- For best results, use this integration with Scheduler rules that define your normal temperature behavior.
- Changes to thermostat `min_temp`/`max_temp` are handled dynamically and the Boost Temperature slider range updates automatically.

## Development Status

Current integration version in `manifest.json`: `0.1.0`.

