"""Constants for the EISUS Home Assistant integration.

EISUS devices running firmware v9.6.6+ expose a token protected local HTTP
API on TCP/80 (firmware BLOCK 31B).  This integration is built exclusively on
that API plus mDNS discovery, so it works with no cloud connection and no MQTT
broker.  The device side "Home Assistant MQTT" client that existed in
v9.6.5 (FIX-72..FIX-77) was removed in v9.6.6 - Home Assistant is now the
only side that speaks the protocol.
"""

DOMAIN = "eisus"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_INFO = "info"

MANUFACTURER = "EISUS"

# --- local HTTP API (firmware BLOCK 31B) -----------------------------------
PATH_INFO = "/local/info"
PATH_STATE = "/local/state"
PATH_CMD = "/local/cmd"
PATH_TIMER = "/local/timer"
PATH_SCHEDULE = "/local/schedule"
PATH_TIME_GET = "/local/time/get"
PATH_TIME_SET = "/local/time/set"

HEADER_TOKEN = "X-Local-Token"

DEFAULT_PORT = 80
SCAN_INTERVAL_S = 4
HTTP_TIMEOUT_S = 6
CMD_RETRIES = 3
# /local/info is re-read on this interval (capabilities, RSSI, cloud state).
INFO_REFRESH_S = 30
# The device clock is pushed to the device from Home Assistant when the
# device reports timeValid=false (no internet -> no NTP), at most this often.
TIME_SYNC_MIN_INTERVAL_S = 60

# --- mDNS ------------------------------------------------------------------
MDNS_SERVICE = "_eisus._tcp.local."
MDNS_REDISCOVER_MIN_INTERVAL_S = 20
MDNS_QUERY_TIMEOUT_MS = 3000

# --- firmware enums (BLOCK 1 / BLOCK 6) -----------------------------------
SWITCH_MODE_TOGGLE = 0
SWITCH_MODE_MOMENTARY = 1
SWITCH_MODE_SHUTTER = 2
SWITCH_MODES = {
    SWITCH_MODE_TOGGLE: "Toggle",
    SWITCH_MODE_MOMENTARY: "Momentary",
    SWITCH_MODE_SHUTTER: "Shutter",
}

POWER_RESTORE_LAST_STATE = 0
POWER_RESTORE_ALL_ON = 1
POWER_RESTORE_ALL_OFF = 2
POWER_RESTORE_MODES = {
    POWER_RESTORE_LAST_STATE: "Last state",
    POWER_RESTORE_ALL_ON: "All on",
    POWER_RESTORE_ALL_OFF: "All off",
}

# Outputs 1 and 3 drive the two shutter motor relays while the device runs in
# shutter mode, so they must not be exposed as plain switches then.
SHUTTER_UP_CHANNEL = 1
SHUTTER_DOWN_CHANNEL = 3

# --- firmware value bounds (BLOCK 6 / BLOCK 10G) --------------------------
PULSE_MIN_DURATION_MS = 50
PULSE_MAX_DURATION_MS = 600000
PULSE_DEFAULT_DURATION_MS = 500
TIMER_MIN_DURATION_MS = 100
TIMER_MAX_MS = 86400000
SHUTTER_MIN_TRAVEL_MS = 500
SHUTTER_MAX_TRAVEL_MS = 120000
MAX_SCHEDULE_RULES = 8
DEFAULT_OUTPUT_COUNT = 4

# --- device types / subtypes ----------------------------------------------
DEVICE_TYPE_SWITCH = "switch"
DEVICE_TYPE_SENSOR = "sensor"
DEVICE_TYPE_PRESENCE = "presence"
DEVICE_TYPE_MOTION = "motion"
DEVICE_SUBTYPE_WALL = "wall"
DEVICE_SUBTYPE_SHUTTER = "shutter"

# Highest output count the firmware can report (BLOCK 1: OUTPUT_COUNT = 4).
MAX_OUTPUTS = 4

# Weekly schedule rule day bitmask (bit0 = Sunday .. bit6 = Saturday), exactly
# as the firmware parses it in scheduleRuleFromJson().
DAY_BITS = {
    "sun": 1,
    "mon": 2,
    "tue": 4,
    "wed": 8,
    "thu": 16,
    "fri": 32,
    "sat": 64,
}
DAY_NAMES = tuple(DAY_BITS)

# --- services --------------------------------------------------------------
SERVICE_SEND_COMMAND = "send_command"
SERVICE_SET_TIME = "set_time"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_CANCEL_TIMER = "cancel_timer"
SERVICE_CALIBRATE_SHUTTER = "calibrate_shutter"

ATTR_ENDPOINT = "endpoint"
ATTR_PAYLOAD = "payload"
ATTR_EPOCH = "epoch"
ATTR_TIMEZONE = "timezone"
ATTR_OFFSET_SEC = "offset_sec"
ATTR_USE_NOW = "use_now"
ATTR_RESOLVE_HOSTNAME = "resolve_hostname"
ATTR_RULES = "rules"
ATTR_OUTPUT = "output"
ATTR_STATE = "state"
ATTR_DURATION_MS = "duration_ms"
ATTR_AFTER_MS = "after_ms"
ATTR_RESTORE_STATE = "restore_state"
ATTR_TIMER_ID = "timer_id"
ATTR_MODE = "mode"
ATTR_ACTION = "action"
ATTR_OPEN_TIME_MS = "open_time_ms"
ATTR_CLOSE_TIME_MS = "close_time_ms"

ENDPOINTS = {
    "cmd": PATH_CMD,
    "timer": PATH_TIMER,
    "schedule": PATH_SCHEDULE,
    "time": PATH_TIME_SET,
}
