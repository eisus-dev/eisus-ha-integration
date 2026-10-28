"""Maintenance buttons for EISUS devices."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .entity import EisusEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    entities = [EisusSyncTimeButton(coord)]
    if coord.device_type == "switch":
        if coord.supports("timer"):
            entities.append(EisusCancelTimersButton(coord))
        if coord.supports("schedule"):
            entities.append(EisusClearScheduleButton(coord))
        if coord.is_shutter_mode:
            entities.append(EisusShutterCalibrateStartButton(coord))
            entities.append(EisusShutterCalibrateEndButton(coord))
    entities.append(EisusFactoryResetButton(coord))
    async_add_entities(entities)


class EisusCancelTimersButton(EisusEntity, ButtonEntity):
    """Cancel the timer / pulse that may be running on any output."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-off"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_cancel_timers"
        self._attr_name = "Cancel all timers"

    async def async_press(self) -> None:
        for output in range(1, self.coord.output_count + 1):
            await self.coord.async_timer_cancel(output)


class EisusClearScheduleButton(EisusEntity, ButtonEntity):
    """Delete every weekly schedule rule stored on the device."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_clear_schedule"
        self._attr_name = "Clear schedule"

    async def async_press(self) -> None:
        await self.coord.async_schedule_clear()


class EisusFactoryResetButton(EisusEntity, ButtonEntity):
    """Wipe credentials and configuration, then reboot the device."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_factory_reset"
        self._attr_name = "Factory reset"

    async def async_press(self) -> None:
        _LOGGER.warning(
            "EISUS %s: factory reset requested from Home Assistant - the device "
            "will erase its credentials and reboot",
            self._did,
        )
        await self.coord.async_factory_reset()


class EisusSyncTimeButton(EisusEntity, ButtonEntity):
    """Push the Home Assistant clock to the device (firmware FIX-82).

    Useful right after a power cut with the internet down: without it the
    device has no clock, so schedules and timers cannot fire until NTP works.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_sync_time"
        self._attr_name = "Sync device time"

    @property
    def available(self) -> bool:
        return super().available and self.coord.supports_time_endpoints

    async def async_press(self) -> None:
        await self.coord.async_set_time()


class EisusShutterCalibrateStartButton(EisusEntity, ButtonEntity):
    """Enter interactive shutter calibration (motor can be jogged)."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter_cal_start"
        self._attr_name = "Shutter calibration start"

    async def async_press(self) -> None:
        _LOGGER.info("EISUS %s: starting shutter calibration", self._did)
        await self.coord.async_shutter_calibrate(mode="start")


class EisusShutterCalibrateEndButton(EisusEntity, ButtonEntity):
    """Leave calibration mode, storing the travel times measured on the device."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter_cal_end"
        self._attr_name = "Shutter calibration end"

    async def async_press(self) -> None:
        _LOGGER.info(
            "EISUS %s: finishing shutter calibration (travel times stored)", self._did
        )
        await self.coord.async_shutter_calibrate(mode="end")
