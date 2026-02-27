# Thermostat Boost for Home Assistant

## Intro

**I developed Thermostat Boost to allow me to temporarily set the temperature of Generic Thermostats (although I suspect it will work with other kinds too - it does for Nests).  When the temporary boost expires, the thermostat reverts to either the last temperature it was set to, or the current schedule if one is defined and is turned on.**

Previously, I had developed a series of automations to achieve this which involved creating numerous helpers for each instance. Adding a new thermostat took some time to do. I wanted to see if I could streamline this as well as test how well ChatGPT could code as this is well beyond my capabilities.

This integration has been designed around my own use case.  I'm happy to take suggestions on board but it's unlikely I'll implement them, no matter how good they sound as I don't have the time to maintain this. I'll try to fix any major bugs or if something stops working due to a new HA release but no promises.  

A few notes:
 
 - The included dashboard card uses [Bubble Card](https://github.com/Clooos/Bubble-Card), [Scheduler Card](https://github.com/nielsfaber/scheduler-card) (and its associated [Scheduler Component](https://github.com/nielsfaber/scheduler-component)), and [Slider Entity Row](https://github.com/thomasloven/lovelace-slider-entity-row).  I have made the Scheduler card optional but you must have Bubble Card and Slider Entity Row installed.
 - I haven't tested it but this should work for both Celcius and Fahrenheit.
 - Certain logic e.g. not being able to change schedules during boosts is enforced using the included card. I don't know how well the boost will handle it if changes are made outside of the card but I expect it will work.

> [!CAUTION]
> Because this was developed by ChatGPT, I have no idea if the code is efficient or uses best practice. I've done a fair bit of testing but I may well have missed issues. I've also rearchitected the way it works and haven't had a chance to test so extensively. Use at own risk!

## Screenshots
### Thermostats summary
![Thermostats summary](https://raw.githubusercontent.com/londondev77/Home-Assistant-Thermostat-booster/refs/heads/main/screenshots/thermostats-summary.png)

### Thermostat detail overlay
![Thermostat detail overlay](https://raw.githubusercontent.com/londondev77/Home-Assistant-Thermostat-booster/refs/heads/main/screenshots/thermostat-detail-overlay.png)

### Integration overview
![Integration overview](https://raw.githubusercontent.com/londondev77/Home-Assistant-Thermostat-booster/refs/heads/main/screenshots/integration-overview.png)

### Integration detail
![Integration detail](https://raw.githubusercontent.com/londondev77/Home-Assistant-Thermostat-booster/refs/heads/main/screenshots/integration-detail.png)

## Features

- Fast temporary heat boost (or reduction) without touching your normal schedule setup (if you have one).
- Automatic return to scheduled control or previous target temperature when boost ends.
- Functionality to set certain thermostats to Call for Heat. An aggregate binary sensor can be used in automations to fire the boiler if your setup allows this. I'm not actually using this but I have tested that the feature works as intended.
- Resilience during Home Assistant restarts or short outages.
- Script and automation friendly services (`start_boost`, `finish_boost`).

## Benefits

- **Easy to set up**.  Add the integration to HACS and then set up a new integration per thermostat. Finally add the associated card to your dashboard (or just use the Services).  Everything else should be taken care of.  It should be quick and easy!
- **Scalable**. Should work with multiple thermostats.
- **Resilient**. Persists across Home Assistant restarts and works even if the boost expires when the server is offline.  This needs further testing as it was difficult to get working properly!
- **Thought through!** I've tried to take into account all the different scenarios where things can go wrong and ensure the integration doesn't fall over. I've also designed the UI to make sense (to me at least).
- **Services/Actions available**. If you don't want to use the supplied dashboard card, you should still be able to boost thermostats with the provided Services.

## Automatic Installation with HACS
1. Add this repository to HACS using the following button
[![open HACS repository on My Home Assistant](https://camo.githubusercontent.com/49f849a6409cdcad49e32d41115ab078f810d960b35466436e028d4552aadd40/68747470733a2f2f6d792e686f6d652d617373697374616e742e696f2f6261646765732f686163735f7265706f7369746f72792e737667) ](https://my.home-assistant.io/redirect/hacs_repository/?owner=londondev77&repository=Home-Assistant-Thermostat-booster&category=integration)
1. Install **Thermostat Boost**.
1. Restart Home Assistant.


## Manual Installation
1. Copy the thermostat_boost directory to /config/custom_components
1. Restart Home Assistant

## Add integration
Click the following button:
[![Add Thermostat Boost integration](https://camo.githubusercontent.com/d8ac4e6e791cd4d420e5438690e66a33b26409d097b26aa0dcc9b60b007484a9/68747470733a2f2f6d792e686f6d652d617373697374616e742e696f2f6261646765732f636f6e6669675f666c6f775f73746172742e737667) ](https://my.home-assistant.io/redirect/config_flow_start/?domain=thermostat_boost)

Or:
1. Go to **Settings -> Devices & Services -> Add Integration**.
1. Select **Thermostat Boost**.
1. Choose the target thermostat from the dropdown.

Repeat for each thermostat you want to control.

> [!NOTE]
> When the first thermostat entry is created, Thermostat Boost also auto-creates a separate device (`Thermostat Boost Call for Heat`) that provides `binary_sensor.thermostat_boost_call_for_heat_active`.

## Optional Lovelace Card

This repository includes `www/thermostat-boost-card.js`, a custom Lovelace card for:

- Thermostat summary
- Boost time/temperature controls
- Start/cancel actions
- Countdown display
- Display/edit/disble schedules
- Enforces some logic by disabling elements when they shouldn't be changed e.g. during a boost

> [!NOTE]
> - The Call for Heat toggle is not included on the dashboard card to save space, as it is expected to be changed infrequently. I also want to avoid accidental toggling.
> - You can change this setting from the thermostat Device Info page in **Settings -> Devices & Services**.

### Installing the Lovelace card
[Click here for instructions on how to install the Lovelace card](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources).

### Adding the Lovelace card to dashboard
1. Edit dashboard and click add card.
1. Search for the Thermostat Boost card.
1. Select the device to add. *Only thermostats you've added to the integration will appear in this list*.
1. Click save.

### Card configuration option

- `Include Scheduler card` (default: enabled):
  - When enabled, the card shows the embedded Scheduler card and the `Disable Schedules` switch.
  - When disabled, both the embedded Scheduler card and `Disable Schedules` switch are hidden.
  - If the selected thermostat already has schedules assigned and this option is disabled, the editor shows a warning recommending that Scheduler card is included to avoid confusion.

## Dependencies

The full feature set depends on these Home Assistant add-ons/custom cards:

| Dependency | Required for | Why it is needed | GitHub |
|---|---|---|---|
| Bubble Card | Required if using `www/thermostat-boost-card.js` | The custom card renders with `custom:bubble-card` (header + pop-up views) | https://github.com/Clooos/Bubble-Card |
| Scheduler Component | Optional | Provides scheduler functionality to the thermostat.  | https://github.com/nielsfaber/scheduler-component |
| Scheduler Card | Optional | Used to show/edit thermostat schedules created by the Scheduler Component | https://github.com/nielsfaber/scheduler-card |
| Slider Entity Row | Required if using `www/thermostat-boost-card.js` | Boost time/temperature controls use `custom:slider-entity-row` | https://github.com/thomasloven/lovelace-slider-entity-row |

> [!NOTE]
> - If you do not use `www/thermostat-boost-card.js`, Bubble Card / Scheduler Card / Slider Entity Row are not required for backend services to run.

## How to use
### Simple boost
UI steps:
1. Click on the thermostat summary card
1. Set the boost temperature and duration
1. Click the `Start Boost` button (this will only be shown when duration is set to a value above 0).

What happens in the background:
1. The current target temperature of the thermostat is snapshotted.
1. The thermostat's schedules (if there are any) are snapshotted and turned off. Matching is based on scheduler switches whose `entities` include the boosted thermostat entity ID. Turning them off is done so they don't override the boost.
1. Thermostat target temperature is changed to match selected boost temperature.
1. Timer is started.
1. Boost runs until timer expires (or until boost is cancelled manually).
1. On finish, the temperature snapshot is restored followed by scheduler snapshot (and those that are switched on will also be passed to the `scheduler.run_action` service to ensure they're enabled correctly).  The latter will override the temperature snapshot if a schedule is active at that point.

> [!NOTE]
> If a single scheduler switch controls multiple thermostats, boosting one thermostat will still toggle that shared scheduler switch and can therefore affect the other thermostats on that schedule.

### Disable Schedules toggle (Long-Term Changes)

Boosts can be set for a maximum of 24 hours set by the UI. If you require an override of the schedule for longer (e.g in the summer or when you're on holiday), use the Disable Schedules toggle.  This will switch schedules off for that thermostat.  You can then set the thermostat to a fixed temperature and use boosts where necessary.  When the boost expires, the thermostat will revert back to the fixed temperature.

You can probably set for longer than 24 hours using the Service but I haven't tried it. 


## Technical information

### Reliability Mitigations (technical)

The integration includes several safeguards:


- Persistent timer state:
  - Timer end times are saved to storage and reloaded after restart.  A timer entity cannot be added to an integration which would have handled this "for free" so the functionality was developed.
  - Expired-during-offline boosts are finished immediately when HA comes back. This is something that couldn't be done with a Timer helper.

- Persistent scheduler snapshot:

  - Turning schedules back on should always immediately set the thermostat to the prevailing schedule if there is one (and this is what I found in my old automation method).  However I found this wasn't always reliable so when the schedules are turned back on, `scheduler.run_action` is also executed to force the schedule. This appears to work well but needs further testing.

- Retry when entities are unavailable:
  - If scheduler entities are `unknown`/`unavailable` during restore, restore is deferred and retried.
  - If a restore service call fails, restore is retried.

- Dynamic boost temperature slider bounds:
  - Reads thermostat `min_temp` and `max_temp` attributes
  - If either value is unavailable/invalid, it is normalised to `0`
  - Default fallback range - metric (`C`): `5-25`, US customary (`F`): `40-80`
  - If both normalized values are `0`, the fallback range is used
  - If `max_temp` is `0` and `min_temp` is > `0`, `max_temp` is set to the fallback max
  - If bounds are inverted (`min_temp > max_temp`), both are reset to the fallback range
  - Updates dynamically when thermostat min/max attributes change (no integration reload required)



- Finish callback fallback:
  - A direct callback path exists in addition to the event listener, reducing risk of missed finish handling.

### Debug Logging

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


### Entities Created

For each thermostat entry:

- `sensor.<thermostat>_boost_finish`. Date/time the boost will end.
- `switch.<thermostat>_boost_active`. A flag to show when a boost is active.
- `number.<thermostat>_boost_temperature`. Boost temperature set in dashboard.
- `number.<thermostat>_boost_time_selector`. Boost duration set in dashboard.
- `switch.<thermostat>_disable_schedules`. A toggle to show the thermostat's schedules have been disabled.
- `switch.<thermostat>_call_for_heat_enabled`. Includes this thermostat in the aggregate call-for-heat signal.

All of the above are hidden by default so they are not shown on automatically generated dashboards. That's the theory anyway.

Additional aggregate device and entity:

- Device: `Thermostat Boost Call for Heat`. A separate device that is created automatically for the integration.
- `binary_sensor.thermostat_boost_call_for_heat_active`. Turns on when at least one call-for-heat-enabled thermostat is actively heating. Use this to trigger your boiler to come on.

(Exact entity IDs depend on your naming/entity registry.)

### Services

#### `thermostat_boost.start_boost`

Starts a boost session.

Inputs:

- `device_id` (required). One device ID or a list of device IDs.
- `time` (optional - see example below for format.  If not specified, Boost Duration slider is used.)
- `temperature` (optional. If not specified,  Boost Temperature slider is used.)

Example:

```yaml
service: thermostat_boost.start_boost
data:
  device_id: 1234567890abcdef1234567890abcdef
  time:
    hours: 1
    minutes: 30
  temperature: 21.0
```

#### `thermostat_boost.finish_boost`

Ends boost and restores scheduler state.

Example:

```yaml
service: thermostat_boost.finish_boost
data:
  device_id: 1234567890abcdef1234567890abcdef
```