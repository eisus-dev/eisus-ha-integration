"""Device clock: the ``eisus.set_time`` service and the ``time`` platform.

Firmware v9.6.6 (FIX-82) exposes POST /local/time/set and GET /local/time/get.
The integration uses them in two ways:

* ``eisus.set_time`` - an automation/script service that pushes the Home
  Assistant clock (or an explicit epoch/timezone) to the device;
* a ``time`` entity that shows the device's clock and lets it be changed from
  the UI.

The device syncs its own clock over NTP, which requires internet.  In a
LAN-only install (or during a cloud outage) the coordinator therefore pushes
Home Assistant's clock whenever the device reports ``time.valid = false``,
which is what keeps the schedule and timer engines working.

The entity platform only exists on Home Assistant 2023.7+; on older versions
the module still registers the service (see TIME_PLATFORM_AVAILABLE).
"""

from __future__ import annotations

import logging
from datetime import time as dt_time

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID, EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_EPOCH,
    ATTR_OFFSET_SEC,
    ATTR_TIMEZONE,
    ATTR_USE_NOW,
    DOMAIN,
    SERVICE_SET_TIME,
)
from .coordinator import coordinator_for_ha_device
from .entity import EisusEntity

_LOGGER = logging.getLogger(__name__)

try:  # homeassistant.components.time exists since Home Assistant 2023.7
    from homeassistant.components.time import TimeEntity

    TIME_PLATFORM_AVAILABLE = True
except ImportError:  # pragma: no cover - only on very old Home Assistant
    TimeEntity = object
    TIME_PLATFORM_AVAILABLE = False


SERVICE_SET_TIME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_USE_NOW, default=True): cv.boolean,
        vol.Optional(ATTR_EPOCH): cv.positive_int,
        vol.Optional(ATTR_TIMEZONE): cv.string,
        vol.Optional(ATTR_OFFSET_SEC): vol.Coerce(int),
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register ``eisus.set_time`` (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_TIME):
        return

    async def _handle_set_time(call: ServiceCall) -> None:
        coord = coordinator_for_ha_device(hass, call.data[ATTR_DEVICE_ID])
        if coord is None:
            raise HomeAssistantError(
                f"EISUS device {call.data[ATTR_DEVICE_ID]} is not configured"
            )
        use_now = call.data.get(ATTR_USE_NOW, True)
        epoch = call.data.get(ATTR_EPOCH)
        if epoch is None and not use_now:
            raise HomeAssistantError(
                "eisus.set_time needs either epoch or use_now: true (the default)"
            )
        # epoch=None tells the coordinator to use the Home Assistant clock.
        await coord.async_set_time(
            epoch=epoch,
            timezone=call.data.get(ATTR_TIMEZONE),
            offset_sec=call.data.get(ATTR_OFFSET_SEC),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TIME, _handle_set_time, schema=SERVICE_SET_TIME_SCHEMA
    )


async def async_setup_entry(hass, entry, async_add_entities):
    """Create the device-clock entity (the `time` platform)."""
    if not TIME_PLATFORM_AVAILABLE:  # pragma: no cover
        _LOGGER.info(
            "EISUS: this Home Assistant has no 'time' platform - use the "
            "eisus.set_time service to set the device clock"
        )
        return
    coord = hass.data[DOMAIN][entry.entry_id]
    if not coord.handler.supports("time"):
        # A future device type may not have a clock at all.
        return
    async_add_entities([EisusDeviceClockTime(coord)])


class EisusDeviceClockTime(EisusEntity, TimeEntity):
    """The device's clock-of-day: read it, and set it from the UI."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_device_clock"
        self._attr_name = "Set device time"

    @property
    def _clock(self) -> dict:
        return self.psub("time")

    @property
    def available(self) -> bool:
        """Unavailable until the firmware answers /local/time/get (FIX-82)."""
        return super().available and self.coord.supports_time_endpoints

    @property
    def native_value(self):
        clock = self._clock
        raw = clock.get("localTime")
        if not clock.get("valid") or not raw:
            return None
        try:
            _, _, hms = str(raw).partition("T")
            hours, minutes, seconds = hms.split(":")
        except ValueError:
            return None
        return dt_time(int(hours), int(minutes), int(float(seconds)))

    @property
    def extra_state_attributes(self):
        clock = self._clock
        return {
            "timezone": clock.get("timezone"),
            "offset_sec": clock.get("offsetSec"),
            "synced": bool(clock.get("valid")),
            "device_epoch": clock.get("epoch"),
        }

    async def async_set_value(self, value) -> None:
        """Set the device clock to `value` on today's date."""
        moment = dt_util.now().replace(
            hour=value.hour, minute=value.minute, second=value.second, microsecond=0
        )
        _LOGGER.debug(
            "EISUS %s: setting the device clock to %s (%s)",
            self.coord.device_key,
            moment.isoformat(),
            int(moment.timestamp()),
        )
        await self.coord.async_set_time(epoch=int(moment.timestamp()))
