"""Diagnostic and time sensors for EISUS devices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import EisusEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    # Diagnostics every device type has (identity + link state from /local/info).
    entities = [
        EisusUptimeSensor(coord),
        EisusDeviceTimeSensor(coord),
        EisusWifiRssiSensor(coord),
        EisusIpAddressSensor(coord),
        EisusCloudLinkSensor(coord),
        EisusLastTriggerSensor(coord),
    ]
    if coord.device_type == "switch":
        entities.append(EisusScheduleCountSensor(coord))
        entities.extend(
            EisusTimerRemainingSensor(coord, output)
            for output in range(1, coord.output_count + 1)
        )
        if coord.is_shutter_mode:
            entities.append(EisusShutterCalibratedSensor(coord))
    async_add_entities(entities)


class EisusUptimeSensor(EisusEntity, SensorEntity):
    """Seconds since the device booted (firmware millis())."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_uptime"
        self._attr_name = "Uptime"

    @property
    def native_value(self):
        try:
            return round(int(self.payload.get("ts") or 0) / 1000, 1)
        except (TypeError, ValueError):
            return None


class EisusDeviceTimeSensor(EisusEntity, SensorEntity):
    """The device's own clock, including the offset it is running with."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_device_time"
        self._attr_name = "Device time"

    @property
    def native_value(self):
        clock = self.psub("time")
        if not clock.get("valid") or not clock.get("localTime"):
            return None
        try:
            naive = datetime.fromisoformat(str(clock["localTime"]))
        except ValueError:
            return None
        try:
            offset = int(clock.get("offsetSec") or 0)
        except (TypeError, ValueError):
            offset = 0
        return naive.replace(tzinfo=timezone(timedelta(seconds=offset)))

    @property
    def extra_state_attributes(self):
        clock = self.psub("time")
        return {
            "timezone": clock.get("timezone"),
            "offset_sec": clock.get("offsetSec"),
            "synced": bool(clock.get("valid")),
        }


class EisusTimerRemainingSensor(EisusEntity, SensorEntity):
    """Remaining time of the timer running on one output."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_timer{output}_remaining"
        self._attr_name = f"Output {output} timer remaining"

    @property
    def _timer(self) -> dict:
        timer = self.psub("timers").get(f"output{self._output}")
        return timer if isinstance(timer, dict) else {}

    @property
    def native_value(self):
        timer = self._timer
        if not timer.get("active"):
            return 0.0
        try:
            return round(int(timer.get("remainingMs") or 0) / 1000, 1)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self):
        timer = self._timer
        return {
            "phase": timer.get("phase"),
            "target_state": timer.get("targetState"),
            "is_pulse": timer.get("isPulse"),
        }


class EisusScheduleCountSensor(EisusEntity, SensorEntity):
    """Number of weekly schedule rules stored on the device."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_schedule_count"
        self._attr_name = "Schedule rules"

    @property
    def native_value(self):
        try:
            return int(self.psub("schedule").get("ruleCount") or 0)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self):
        rules = self.psub("schedule").get("rules") or []
        return {
            "rules": [
                {
                    "id": rule.get("id"),
                    "enabled": rule.get("enabled"),
                    "days": rule.get("days"),
                    "start_min": rule.get("startMin"),
                    "end_min": rule.get("endMin"),
                    "active_now": rule.get("activeNow"),
                    "outputs": rule.get("outputs"),
                }
                for rule in rules
                if isinstance(rule, dict)
            ]
        }


class EisusLastTriggerSensor(EisusEntity, SensorEntity):
    """What caused the device to publish its most recent state."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_last_trigger"
        self._attr_name = "Last state trigger"

    @property
    def native_value(self):
        return self.payload.get("trigger")


# ---------------------------------------------------------------------------
# Device / link diagnostics, all sourced from /local/info (FIX-82 fields)
# ---------------------------------------------------------------------------


class EisusWifiRssiSensor(EisusEntity, SensorEntity):
    """Wi-Fi signal strength of the device (dBm)."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "dBm"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_wifi_rssi"
        self._attr_name = "Wi-Fi signal"

    @property
    def native_value(self):
        value = self.coord.info.get("rssi")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class EisusIpAddressSensor(EisusEntity, SensorEntity):
    """LAN address the device currently answers on."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ip-network"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_ip"
        self._attr_name = "IP address"

    @property
    def native_value(self):
        return self.coord.info.get("ip") or self.coord.host


class EisusCloudLinkSensor(EisusEntity, SensorEntity):
    """The device's own cloud link: online / offline / no internet."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_cloud_link"
        self._attr_name = "Cloud link"

    @property
    def native_value(self):
        info = self.coord.info
        if info.get("mqttOnline"):
            return "online"
        if info.get("inetReachable"):
            return "cloud offline"
        return "no internet"

    @property
    def extra_state_attributes(self):
        info = self.coord.info
        return {
            "mqtt_online": bool(info.get("mqttOnline")),
            "inet_reachable": bool(info.get("inetReachable")),
        }


class EisusShutterCalibratedSensor(EisusEntity, SensorEntity):
    """Whether the shutter travel times are known (position control works)."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter_calibrated"
        self._attr_name = "Shutter calibration"

    @property
    def _shutter(self) -> dict:
        return self.psub("shutter")

    @property
    def native_value(self):
        return "calibrated" if self._shutter.get("calibrated") else "not calibrated"

    @property
    def extra_state_attributes(self):
        shutter = self._shutter
        return {
            "open_time_ms": shutter.get("openTimeMs"),
            "close_time_ms": shutter.get("closeTimeMs"),
        }
