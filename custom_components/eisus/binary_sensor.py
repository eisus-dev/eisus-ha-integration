"""Binary sensors for EISUS devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import EisusEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    entities = [EisusCloudReachableBinarySensor(coord)]
    if coord.device_type == "switch":
        if coord.supports("timer"):
            for output in range(1, coord.output_count + 1):
                entities.append(EisusTimerActiveBinarySensor(coord, output))
                entities.append(EisusManualOverrideBinarySensor(coord, output))
        if coord.is_shutter_mode:
            entities.append(EisusShutterMovingBinarySensor(coord))
            entities.append(EisusShutterCalibratingBinarySensor(coord))
    else:
        # Sensor devices (presence / motion): one primary binary state.
        entities.append(EisusPrimaryBinarySensor(coord))
    async_add_entities(entities)


class EisusTimerActiveBinarySensor(EisusEntity, BinarySensorEntity):
    """Reports whether a timer (or pulse) is currently running on an output."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_timer{output}_active"
        self._attr_name = f"Output {output} timer active"

    @property
    def _timer(self) -> dict:
        timer = self.psub("timers").get(f"output{self._output}")
        return timer if isinstance(timer, dict) else {}

    @property
    def is_on(self) -> bool:
        return bool(self._timer.get("active"))

    @property
    def extra_state_attributes(self):
        return {"phase": self._timer.get("phase")}


class EisusManualOverrideBinarySensor(EisusEntity, BinarySensorEntity):
    """True while manual control wins over the running schedule on an output."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_override{output}"
        self._attr_name = f"Output {output} manual override"

    @property
    def is_on(self) -> bool:
        return bool(self.psub("manualOverride").get(f"output{self._output}"))


class EisusShutterMovingBinarySensor(EisusEntity, BinarySensorEntity):
    """True while the shutter motor is running."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.MOVING

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter_moving"
        self._attr_name = "Shutter moving"

    @property
    def is_on(self) -> bool:
        return bool(self.psub("shutter").get("moving"))


class EisusShutterCalibratingBinarySensor(EisusEntity, BinarySensorEntity):
    """True while the device is in interactive shutter calibration mode."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter_calibrating"
        self._attr_name = "Shutter calibrating"

    @property
    def is_on(self) -> bool:
        return bool(self.psub("shutter").get("calibrating"))


class EisusCloudReachableBinarySensor(EisusEntity, BinarySensorEntity):
    """True when the device itself can reach the EISUS cloud.

    Purely diagnostic: local control through this integration does not depend
    on it, so the entity is disabled by default to keep dashboards clean.
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_cloud_reachable"
        self._attr_name = "Cloud reachable"

    @property
    def is_on(self) -> bool:
        return bool(self.coord.info.get("inetReachable"))

    @property
    def extra_state_attributes(self):
        info = self.coord.info
        return {
            "mqtt_online": bool(info.get("mqttOnline")),
            "fw_version": info.get("fwVersion"),
            "hw_version": info.get("hwVersion"),
        }


class EisusPrimaryBinarySensor(EisusEntity, BinarySensorEntity):
    """Primary state of a sensor-type device (presence, motion, ...).

    Which /local/state keys are watched is decided by the device-type handler
    (device_registry.SensorDeviceHandler.primary_keys), so a new sensor type
    needs no change here.
    """

    _attr_should_poll = False

    _DEVICE_CLASSES = {
        "presence": getattr(BinarySensorDeviceClass, "PRESENCE", None),
        "motion": getattr(BinarySensorDeviceClass, "MOTION", None),
    }

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_primary"
        # Take the device name itself: this is the device's main entity.
        self._attr_name = None
        self._attr_device_class = self._DEVICE_CLASSES.get(coord.device_type)

    @property
    def is_on(self):
        return self.coord.state_view.get("primary")
