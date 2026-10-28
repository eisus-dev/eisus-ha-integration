"""Device type registry for the EISUS integration.

The firmware tells the integration what it is (`type`, `subtype`, `fwVersion`,
`hwVersion`, `outputCount` and a `capabilities` object in `/local/info`).  This
module turns that description into the concrete behaviour of the integration:

* which Home Assistant entity platforms are created for the device,
* what the device can do (`supports()`),
* how the device's `/local/state` document is normalised (`parse_state()`),
* how a logical action becomes an HTTP endpoint + JSON payload
  (`build_command()`).

Adding a new device type is a single-file change: subclass :class:`DeviceHandler`
and register it in :data:`DEVICE_TYPES`.  Nothing else in the integration has to
change - the coordinator resolves the handler on every refresh, the config entry
asks it for the platform list, and the entity platforms ask it about
capabilities.  See README.md ("Adding a new device type").
"""

from __future__ import annotations

import logging

from .const import (
    DEFAULT_OUTPUT_COUNT,
    DEVICE_SUBTYPE_SHUTTER,
    DEVICE_TYPE_MOTION,
    DEVICE_TYPE_PRESENCE,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_SWITCH,
    MAX_OUTPUTS,
    PATH_CMD,
    PATH_SCHEDULE,
    PATH_TIMER,
    PATH_TIME_SET,
    SWITCH_MODE_SHUTTER,
)

_LOGGER = logging.getLogger(__name__)

# Every platform the integration can provide.  A handler picks the subset it
# needs; "time" is dropped automatically on Home Assistant versions that do not
# ship the time platform (see __init__.py).
ALL_PLATFORMS = (
    "switch",
    "select",
    "number",
    "cover",
    "time",
    "sensor",
    "binary_sensor",
    "button",
)


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



class DeviceHandler:
    """Base class describing one firmware device type."""

    device_type: str = ""
    label: str = "EISUS device"
    #: entity platforms forwarded for this device type
    platforms: tuple = ("sensor", "binary_sensor", "button")
    #: capabilities assumed when the firmware sends no `capabilities` object
    default_features: dict = {}

    def __init__(self, info=None, state=None):
        self.info = dict(info or {})
        self.state = dict(state or {})

    def update(self, info=None, state=None) -> "DeviceHandler":
        """Refresh the cached documents (called by the coordinator)."""
        if info:
            self.info = dict(info)
        if state is not None:
            self.state = dict(state)
        return self

    # ---------------------------------------------------------------- identity

    @property
    def subtype(self) -> str:
        return str(self.info.get("subtype") or "").strip().lower()

    @property
    def model(self) -> str:
        """Model string shown on the Home Assistant device page."""
        subtype = self.info.get("subtype")
        return f"{self.device_type}/{subtype}" if subtype else self.device_type

    @property
    def name(self) -> str:
        return str(self.info.get("name") or "").strip()

    # ------------------------------------------------------------ capabilities

    def supports(self, feature: str) -> bool:
        """Whether this device exposes ``feature``.

        The firmware's `capabilities` object wins when present; otherwise the
        handler's static defaults apply, so a device running pre-FIX-82
        firmware (no capabilities object) still gets its full entity set
        instead of silently losing entities.
        """
        caps = self.info.get("capabilities")
        if isinstance(caps, dict) and feature in caps:
            return bool(caps[feature])
        return bool(self.default_features.get(feature, False))

    @property
    def output_count(self) -> int:
        """Number of relay channels: info first, state keys as a fallback."""
        candidates = [self.info.get("outputCount")]
        caps = self.info.get("capabilities")
        if isinstance(caps, dict):
            candidates.append(caps.get("outputs"))
        for candidate in candidates:
            count = _as_int(candidate)
            if count and count > 0:
                return max(1, min(count, MAX_OUTPUTS))
        keys = [k for k in self.state if k.startswith("output") and k[6:].isdigit()]
        return max((int(k[6:]) for k in keys), default=DEFAULT_OUTPUT_COUNT)

    @property
    def is_shutter(self) -> bool:
        """True when the device drives a shutter motor."""
        return False

    # ------------------------------------------------------------------ state

    def parse_state(self, state: dict) -> dict:
        """Normalise ``/local/state`` into the view the entities consume."""
        state = dict(state or {})
        # Keep the cached document in sync: output_count() reads self.state.
        self.state = state
        return {
            "outputs": {
                f"output{n}": bool(state.get(f"output{n}"))
                for n in range(1, self.output_count + 1)
            },
            "switch_mode": _as_int(state.get("switchMode"), 0),
            "child_lock": bool(state.get("childLock")),
            "power_restore": _as_int(state.get("powerRestore"), 0),
        }

    # --------------------------------------------------------------- commands

    def build_command(self, action: str, **kwargs) -> tuple:
        """Map a logical action to ``(endpoint, json_payload)``.

        Handlers override or extend this; the coordinator and the services use
        it, so a new device type only has to describe its own commands here.
        """
        if action == "factory_reset":
            return PATH_CMD, {"command": "factoryreset"}
        if action == "timer_cancel":
            return PATH_TIMER, {"output": int(kwargs["output"]), "cancel": True}
        if action == "schedule":
            return PATH_SCHEDULE, dict(kwargs.get("payload") or {})
        if action == "time_set":
            payload = {"epoch": int(kwargs["epoch"])}
            if kwargs.get("timezone"):
                payload["timezone"] = kwargs["timezone"]
            if kwargs.get("offset_sec") is not None:
                payload["offsetSec"] = int(kwargs["offset_sec"])
            return PATH_TIME_SET, payload
        raise ValueError(f"{self.device_type}: unsupported action '{action}'")


class SwitchDeviceHandler(DeviceHandler):
    """Wall switch modules: 1..4 relay outputs plus the configuration engine."""

    device_type = DEVICE_TYPE_SWITCH
    label = "EISUS switch module"
    platforms = (
        "switch",
        "select",
        "number",
        "cover",
        "time",
        "sensor",
        "binary_sensor",
        "button",
    )
    default_features = {
        "outputs": True,
        "pulse": True,
        "timer": True,
        "schedule": True,
        "time": True,
        "shutter": True,
        "childlock": True,
        "powerrestore": True,
        "switchmode": True,
    }

    @property
    def is_shutter(self) -> bool:
        """Shutter when the subtype says so, or when switchMode is 2."""
        if self.subtype == DEVICE_SUBTYPE_SHUTTER:
            return True
        mode = _as_int(self.state.get("switchMode", self.info.get("switchMode")))
        return mode == SWITCH_MODE_SHUTTER

    def parse_state(self, state: dict) -> dict:
        view = super().parse_state(state)
        state = dict(state or {})
        shutter = state.get("shutter")
        shutter = shutter if isinstance(shutter, dict) else {}
        view["shutter"] = {
            "calibrated": bool(shutter.get("calibrated")),
            "position": _as_int(shutter.get("position")),
            "moving": bool(shutter.get("moving")),
            "calibrating": bool(shutter.get("calibrating")),
            "open_time_ms": _as_int(shutter.get("openTimeMs"), 0),
            "close_time_ms": _as_int(shutter.get("closeTimeMs"), 0),
        }
        schedule = state.get("schedule")
        schedule = schedule if isinstance(schedule, dict) else {}
        view["schedule_rule_count"] = _as_int(schedule.get("ruleCount"), 0)
        timers = state.get("timers")
        timers = timers if isinstance(timers, dict) else {}
        view["timers"] = {
            f"output{n}": (timers.get(f"output{n}") or {})
            for n in range(1, self.output_count + 1)
        }
        view["pulse"] = state.get("pulse") if isinstance(state.get("pulse"), dict) else {}
        return view

    def build_command(self, action: str, **kwargs) -> tuple:
        if action == "output":
            return PATH_CMD, {f"output{int(kwargs['output'])}": bool(kwargs["on"])}
        if action == "switch_mode":
            return PATH_CMD, {"switchmode": int(kwargs["mode"])}
        if action == "child_lock":
            return PATH_CMD, {"childlock": bool(kwargs["locked"])}
        if action == "power_restore":
            return PATH_CMD, {"powerRestore": int(kwargs["mode"])}
        if action == "pulse":
            payload = {
                "enabled": bool(kwargs["enabled"]),
                "durationMs": int(kwargs["duration_ms"]),
            }
            if kwargs.get("output") is not None:
                payload["output"] = int(kwargs["output"])
            return PATH_CMD, {"pulseMode": payload}
        if action == "shutter":
            return PATH_CMD, {"shutter": str(kwargs["shutter_action"])}
        if action == "shutter_position":
            return PATH_CMD, {"shutterPosition": int(kwargs["position"])}
        if action == "shutter_calibrate":
            payload = {}
            if kwargs.get("mode"):
                payload["mode"] = str(kwargs["mode"])
            # NB: named calibration_action (not "action") because `action` is
            # the name of this method's own parameter.
            if kwargs.get("calibration_action"):
                payload["action"] = str(kwargs["calibration_action"])
            if kwargs.get("open_time_ms") is not None:
                payload["openTimeMs"] = int(kwargs["open_time_ms"])
            if kwargs.get("close_time_ms") is not None:
                payload["closeTimeMs"] = int(kwargs["close_time_ms"])
            return PATH_CMD, {"shutterCalibrate": payload}
        return super().build_command(action, **kwargs)


class SensorDeviceHandler(DeviceHandler):
    """Base class for the future sensor devices (presence, motion, ...).

    These devices have no relay outputs: they report one primary binary state
    plus a configuration block.  The entity surface is deliberately small - a
    binary sensor for the primary state, diagnostic sensors and the shared
    maintenance buttons - and grows by overriding :meth:`primary_state`,
    :meth:`parse_state` and :meth:`build_command` in a subclass.
    """

    device_type = DEVICE_TYPE_SENSOR
    label = "EISUS sensor"
    platforms = ("binary_sensor", "sensor", "button")
    default_features = {
        "time": True,
        "config": True,
        "timer": False,
        "schedule": False,
        "outputs": False,
    }

    #: keys checked in /local/state (flat first, then inside a nested object)
    primary_keys = ("state", "presence", "motion", "occupied", "detected", "active")

    def primary_state(self):
        """True / False / None for the device's primary binary state."""
        for key in self.primary_keys:
            if key in self.state and isinstance(self.state[key], (bool, int)):
                return bool(self.state[key])
        nested = self.state.get(self.device_type)
        if isinstance(nested, dict):
            for key in self.primary_keys:
                if key in nested and isinstance(nested[key], (bool, int)):
                    return bool(nested[key])
        return None

    def parse_state(self, state: dict) -> dict:
        view = super().parse_state(state)
        view["primary"] = self.primary_state()
        view["battery"] = _as_int(state.get("battery") if state else None)
        return view

    def build_command(self, action: str, **kwargs) -> tuple:
        if action == "config":
            return PATH_CMD, dict(kwargs.get("payload") or {})
        return super().build_command(action, **kwargs)


class PresenceSensorHandler(SensorDeviceHandler):
    """Presence sensor (future hardware: mmWave / PIR)."""

    device_type = DEVICE_TYPE_PRESENCE
    label = "EISUS presence sensor"
    primary_keys = ("presence", "occupied", "state", "detected")


class MotionSensorHandler(SensorDeviceHandler):
    """Motion sensor (future hardware)."""

    device_type = DEVICE_TYPE_MOTION
    label = "EISUS motion sensor"
    primary_keys = ("motion", "detected", "state", "active")


#: type (from /local/info) -> handler class
DEVICE_TYPES = {
    DEVICE_TYPE_SWITCH: SwitchDeviceHandler,
    DEVICE_TYPE_SENSOR: SensorDeviceHandler,
    DEVICE_TYPE_PRESENCE: PresenceSensorHandler,
    DEVICE_TYPE_MOTION: MotionSensorHandler,
}


def resolve_handler(info=None, state=None) -> DeviceHandler:
    """Return the handler for a device description.

    Unknown types fall back to the switch handler (the shipped hardware) so a
    device reporting a type this integration version does not know yet still
    gets a working, if generic, entity set.
    """
    key = str((info or {}).get("type") or "").strip().lower()
    cls = DEVICE_TYPES.get(key)
    if cls is None:
        if key:
            _LOGGER.info(
                "EISUS: unknown device type '%s' - using the switch handler", key
            )
        cls = SwitchDeviceHandler
    return cls(info, state)


def platforms_for(handler: DeviceHandler, available=ALL_PLATFORMS) -> list:
    """Handler platforms, filtered by what this Home Assistant can provide."""
    return [p for p in handler.platforms if p in available]
