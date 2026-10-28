"""Shutter cover for EISUS devices running in shutter mode."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .const import DOMAIN
from .entity import EisusEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    if not coord.is_shutter_mode:
        # The two motor relays are plain switches while the device is not in
        # shutter mode; switching modes triggers an entry reload.
        return
    async_add_entities([EisusShutterCover(coord)])


class EisusShutterCover(EisusEntity, CoverEntity):
    """Open / close / stop plus (when calibrated) absolute positioning."""

    _attr_should_poll = False
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_shutter"
        # Primary feature of the device: take the device name itself.
        self._attr_name = None

    @property
    def _shutter(self) -> dict:
        return self.psub("shutter")

    @property
    def _calibrated(self) -> bool:
        return bool(self._shutter.get("calibrated"))

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        if self._calibrated:
            features |= CoverEntityFeature.SET_POSITION
        return features

    @property
    def current_cover_position(self):
        try:
            position = int(self._shutter.get("position"))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, position))

    @property
    def is_closed(self):
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def extra_state_attributes(self):
        shutter = self._shutter
        return {
            "calibrated": bool(shutter.get("calibrated")),
            "open_time_ms": shutter.get("openTimeMs"),
            "close_time_ms": shutter.get("closeTimeMs"),
            "moving": bool(shutter.get("moving")),
            "calibrating": bool(shutter.get("calibrating")),
        }

    async def async_open_cover(self, **kwargs):
        await self.coord.async_shutter("open")

    async def async_close_cover(self, **kwargs):
        await self.coord.async_shutter("close")

    async def async_stop_cover(self, **kwargs):
        await self.coord.async_shutter("stop")

    async def async_set_cover_position(self, **kwargs):
        await self.coord.async_set_shutter_position(int(kwargs["position"]))
