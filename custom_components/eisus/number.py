"""Numeric configuration entities for EISUS devices."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory

from .const import (
    DOMAIN,
    PULSE_MAX_DURATION_MS,
    PULSE_MIN_DURATION_MS,
    SHUTTER_MAX_TRAVEL_MS,
    SHUTTER_MIN_TRAVEL_MS,
)
from .entity import EisusEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    if coord.device_type != "switch":
        return
    entities = []
    if coord.supports("pulse"):
        entities.extend(
            EisusPulseDurationNumber(coord, output)
            for output in range(1, coord.output_count + 1)
        )
    if coord.is_shutter_mode:
        entities.append(EisusShutterTravelNumber(coord, "open"))
        entities.append(EisusShutterTravelNumber(coord, "close"))
    async_add_entities(entities)


class EisusPulseDurationNumber(EisusEntity, NumberEntity):
    """How long a channel stays on in pulse / gate-opener mode."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = float(PULSE_MIN_DURATION_MS)
    _attr_native_max_value = float(PULSE_MAX_DURATION_MS)
    _attr_native_step = 50.0
    _attr_native_unit_of_measurement = "ms"
    _attr_mode = NumberMode.BOX

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_pulse{output}_duration"
        self._attr_name = f"Output {output} pulse duration"

    @property
    def _cfg(self) -> dict:
        cfg = self.psub("pulse").get(f"output{self._output}")
        return cfg if isinstance(cfg, dict) else {}

    @property
    def native_value(self):
        try:
            value = int(self._cfg.get("durationMs") or 0)
        except (TypeError, ValueError):
            return None
        return float(value) if value > 0 else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coord.async_set_pulse(
            self._output, bool(self._cfg.get("enabled")), int(value)
        )


class EisusShutterTravelNumber(EisusEntity, NumberEntity):
    """Full travel time of the shutter, as stored by the firmware.

    The firmware's shutterCalibrate command accepts openTimeMs and closeTimeMs
    only as a pair, so writing one value re-sends the other. When the
    counterpart has never been calibrated it is sent as the firmware minimum
    (500 ms), which means the accepted procedure is: set one value, then set
    the other one.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = float(SHUTTER_MIN_TRAVEL_MS)
    _attr_native_max_value = float(SHUTTER_MAX_TRAVEL_MS)
    _attr_native_step = 100.0
    _attr_native_unit_of_measurement = "ms"
    _attr_mode = NumberMode.BOX

    def __init__(self, coord, which: str):
        super().__init__(coord)
        self._which = which
        self._attr_unique_id = f"{self._did}_shutter_{which}_ms"
        self._attr_name = (
            "Shutter open time" if which == "open" else "Shutter close time"
        )

    @property
    def _shutter(self) -> dict:
        return self.psub("shutter")

    def _raw(self, key: str) -> int:
        try:
            return int(self._shutter.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def native_value(self):
        raw = self._raw("openTimeMs" if self._which == "open" else "closeTimeMs")
        return float(raw) if raw >= SHUTTER_MIN_TRAVEL_MS else None

    async def async_set_native_value(self, value: float) -> None:
        open_ms = self._raw("openTimeMs")
        close_ms = self._raw("closeTimeMs")
        if self._which == "open":
            open_ms = int(value)
        else:
            close_ms = int(value)

        placeholder = False
        if open_ms < SHUTTER_MIN_TRAVEL_MS:
            open_ms = SHUTTER_MIN_TRAVEL_MS
            placeholder = True
        if close_ms < SHUTTER_MIN_TRAVEL_MS:
            close_ms = SHUTTER_MIN_TRAVEL_MS
            placeholder = True
        if placeholder:
            _LOGGER.warning(
                "EISUS: the counterpart shutter travel time is not calibrated "
                "yet; sending %s ms as a placeholder - set the other value next.",
                SHUTTER_MIN_TRAVEL_MS,
            )
        await self.coord.async_set_shutter_travel(open_ms, close_ms)
