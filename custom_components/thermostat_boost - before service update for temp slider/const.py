"""Constants for the Thermostat Boost integration."""

DOMAIN = "thermostat_boost"

CONF_THERMOSTAT = "thermostat"
CONF_ENTRY_TYPE = "entry_type"

DATA_THERMOSTAT_NAME = "thermostat_name"

EVENT_TIMER_FINISHED = "thermostat_boost_timer_finished"
SERVICE_START_BOOST = "start_boost"
SERVICE_FINISH_BOOST = "finish_boost"

ENTRY_TYPE_THERMOSTAT = "thermostat"
ENTRY_TYPE_AGGREGATE = "aggregate_call_for_heat"

UNIQUE_ID_TIME_SELECTOR = "boost_time_selector"
UNIQUE_ID_BOOST_TEMPERATURE = "boost_temperature"
UNIQUE_ID_BOOST_ACTIVE = "boost_active"
UNIQUE_ID_BOOST_FINISH = "boost_finish"
UNIQUE_ID_SCHEDULE_OVERRIDE = "disable_schedules"
UNIQUE_ID_CALL_FOR_HEAT_ENABLED = "call_for_heat_enabled"
