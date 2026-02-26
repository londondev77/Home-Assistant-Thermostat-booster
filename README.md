# Thermostat Boost for Home Assistant

## Intro

**I developed Thermostat Boost to allow me to temporarily set the temperature of Generic Thermostats (although I suspect it will work with other kinds too - it does for Nests).  When the temporary boost expires, the thermostat reverts to either the last temperature it was set to, or the current schedule if one is defined and is turned on.**

Previously, I had developed a series of automations to achieve this which involved creating numerous helpers for each instance. Adding a new thermostat took some time to do. I wanted to see if I could streamline this as well as test how well ChatGPT could code as this is well beyond my capabilities.

This integration has been designed around my own use case.  I'm happy to take suggestions on board but it's unlikely I'll implement them, no matter how good they sound as I don't have the time to maintain this. I'll try to fix any major bugs or if something stops working due to a new HA release.  

A few notes:
 
 - The included dashboard card uses [Bubble Card](https://github.com/Clooos/Bubble-Card), [Scheduler Card](https://github.com/nielsfaber/scheduler-card) (and its associated [Scheduler Component](https://github.com/nielsfaber/scheduler-component)), and [Slider Entity Row](https://github.com/thomasloven/lovelace-slider-entity-row).  If you don't have these installed, the provided card will not render well. I don't intend to make this modular to be more flexible.
 - ChatGPT implemented some C to F conversion which I realised wasn't needed so it's been stripped out.  This should work for the US but I can't be sure and it's untested
 - Certain logic e.g. changing active schedules during boosts is enforced using the included card. I don't know how well the Actions will handle it if changes are made outside of the card but I expect it will work.

> [!CAUTION]
> Because this was developed by ChatGPT, I have no idea if the code is efficient or uses best practice. I've done a fair bit of testing but I may well have missed issues. I've also rearchitected the way it works and haven't had a chance to test so extensively. Use at own risk!

> [!Warning]
> I had a few strange things happen after I added the Call for Heat functionality and haven't been able to test installing completely freshly. After installing, a Thermostat Boost Call for Heat device should be added to the integration along with a Call for Heat active entity. If this doesn't happen and/or you find the entity attached to one of the thermostats, let me know.

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

- Fast temporary heat boost (or reduction) without touching your normal schedule setup.
- Automatic return to scheduled control or previous target temperature when boost ends.
- Functionality to set certain thermostats to Call for Heat. An aggregate binary sensor can be used in automations to fire the boiler if your setup allows this. I'm not actually using this but I have tested that the feature works as intended.
- Resilience during Home Assistant restarts or short outages.
- Consistent workflow across multiple thermostats (one integration entry per thermostat).
- Script and automation friendly services (`start_boost`, `finish_boost`).

## Benefits

- **Easy to set up**.  Add the integration to HACS and then set up a new integration per thermostat. Then add the associated card.  Everything else should be taken care of.  It should be quick and easy!
- **Scalable**. Should work with multiple thermostats.
- **Resilient**. Persists across Home Assistant restarts and works even if the boost expires when the server is offline.  This needs further testing as it was difficult to get working properly!
- **Thought through!** I've tried to take into account all the different scenarios where things can go wrong and ensure the integration doesn't fall over. I've also designed the UI to make sense (to me at least).
- **Actions available**. If you don't want to use the supplied dashboard card, you should still be able to boost thermostats with the provided actions.

## Automatic Installation with HACS
1. Add this repository to HACS using the following button
[![open HACS repository on My Home Assistant](https://camo.githubusercontent.com/49f849a6409cdcad49e32d41115ab078f810d960b35466436e028d4552aadd40/68747470733a2f2f6d792e686f6d652d617373697374616e742e696f2f6261646765732f686163735f7265706f7369746f72792e737667) ](https://my.home-assistant.io/redirect/hacs_repository/?owner=londondev77&repository=Home-Assistant-Thermostat-booster&category=integration)
1. Install **Thermostat Boost**.
1. Restart Home Assistant.


## Manual Installation
]1. Copy the thermostat_boost directory to /config/custom_components
1. Restart Home Assistant

## Add integration
Click the following button:
[![Add Thermostat Boost integration](https://camo.githubusercontent.com/d8ac4e6e791cd4d420e5438690e66a33b26409d097b26aa0dcc9b60b007484a9/68747470733a2f2f6d792e686f6d652d617373697374616e742e696f2f6261646765732f636f6e6669675f666c6f775f73746172742e737667) ](https://my.home-assistant.io/redirect/config_flow_start/?domain=thermostat_boost)

Or:
1. Go to **Settings -> Devices & Services -> Add Integration**.
1. Select **Thermostat Boost**.
1. Choose the target thermostat from the dropdown.

Repeat steps 4-6 for each thermostat you want to control.

When the first thermostat entry is created, Thermostat Boost also auto-creates a separate device (`Thermostat Boost Call for Heat`) that provides `binary_sensor.thermostat_boost_call_for_heat_active`.

## Optional Lovelace Card

This repository includes `www/thermostat-boost-card.js`, a custom Lovelace card for:

- thermostat summary
- boost time/temperature controls
- start/cancel actions
- countdown display
- display/edit/disble schedules
- set thermostat to be able to Call for Heat
- enforces some logic by disabling elements when they shouldn't be changed

If you use it, add the JS resource in Dashboard resources and configure the card with the relevant Thermostat Boost device. [Click here for instructions on how to do this](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources).

### Adding the Lovelace card to dashboard
1. Edit dashboard and click add card.
1. Search for the Thermostat Boost card.
1. Select the device to add. *Only thermostats you've added to the integration will appear in this list*.
1. Click save.

## Dependencies

The integration backend itself has no external Python package requirements in `manifest.json`, but the full feature set depends on these Home Assistant add-ons/custom cards:

| Dependency | Required for | Why it is needed | GitHub |
|---|---|---|---|
| Bubble Card | Required if using `www/thermostat-boost-card.js` | The custom card renders with `custom:bubble-card` (header + pop-up views) | https://github.com/Clooos/Bubble-Card |
| Scheduler Component | Recommended (required for schedule pause/restore logic) | Provides `switch` entities on platform `scheduler` that are snapshotted/restored during boost | https://github.com/nielsfaber/scheduler-component |
| Scheduler Card | Required if using `www/thermostat-boost-card.js` | The custom card embeds `custom:scheduler-card` to show/edit thermostat schedules | https://github.com/nielsfaber/scheduler-card |
| Slider Entity Row | Required if using `www/thermostat-boost-card.js` | Boost time/temperature controls use `custom:slider-entity-row` | https://github.com/thomasloven/lovelace-slider-entity-row |

Notes:

- `scheduler-card` is designed to work with `scheduler-component`; if you use the card, install both.
- If you do not use `www/thermostat-boost-card.js`, Bubble Card / Scheduler Card / Slider Entity Row are not required for backend services to run.

## How to use
### Simple boost
UI steps:
1. Click on the thermostat summary card
1. Set the boost temperature and duration
1. Click the `Start Boost` button (this will only be shown when duration is set to a value above 0).

What happens in the background:
1. The current target temperature of the thermostat is snapshotted.
1. Matching scheduler switches are snapshotted and turned off.  This is done so they don't override the boost.
1. Thermostat target temperature is changed to match selected boost temperature.
1. Timer is started.
1. Boost runs until timer expires (or until boost is cancelled manually).
1. On finish, temperature snapshot is restored followed by scheduler snapshot (and those that are switched on will also be passed to the `scheduler.run_action` service to ensure they're enabled correctly).  The latter will override the temperature snapshot if a schedule is active at that point.

Services can also be used if you don't use the dashboard card provided.  More detail can be found in the technical information section.


### Disable Schedules toggle (Long-Term Changes)

Boosts can be set for a maximum of 24 hours. If you require an override of the schedule for longer (e.g in the summer or when you're on holiday), use the Disable Schedules toggle.  This will switch them off.  You can then set the thermostat to a fixed temperature and use boosts where necessary.  When the boost expires, the thermostat will revert back to the fixed temperature.


## Technical information

### Reliability Mitigations (technical)

The integration includes several safeguards:


- Persistent timer state:
  - Timer end times are saved to storage and reloaded after restart.  It doesn't look like a timer entity can be added to an integration which would have handled this "for free" so the functionality was developed.
  - Expired-during-offline boosts are finished immediately when HA comes back.

- Persistent scheduler snapshot:
  - Schedules need to be turned off when a boost is active to ensure the schedules don't override the boost.
  - Before disabling schedules, current Scheduler switch states are stored.
  - Stored snapshot is used to restore the exact previous on/off states at boost end.
  - Turning these schedules back on should always immediately set the thermostat to the prevailing schedule (and this is what I found in my old automation method).  However I found this wasn't always reliable so when the schedules are turned back on, `scheduler.run_action` is also executed to force the schedule. This appears to work well but needs further testing.

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

## Known Behavior

- Boost stores a pre-boost thermostat target temperature snapshot on first start.
- Boost end always attempts scheduler state restore when a scheduler snapshot exists unless Disable Schedules is switched on.
- Boost scheduler-path finish applies pre-boost temperature snapshot first (if present).
- After scheduler restore, `scheduler.run_action` is called for schedules restored to ON.
- Scheduler action may override the pre-boost temperature restore when an applicable schedule action exists.
- For best results, use this integration with Scheduler rules that define your normal temperature behavior.
- Changes to thermostat `min_temp`/`max_temp` are handled dynamically and the Boost Temperature slider range updates automatically.

