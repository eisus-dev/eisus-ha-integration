"""Output, pulse-mode and child-lock switches for EISUS devices."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .const import (
    DOMAIN,
    PULSE_DEFAULT_DURATION_MS,
    PULSE_MIN_DURATION_MS,
    SHUTTER_DOWN_CHANNEL,
    SHUTTER_UP_CHANNEL,
)
from .entity import EisusEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    if coord.device_type != "switch":
        # Sensor-type devices have no relay outputs (see device_registry.py).
        return

    entities = []
    for output in range(1, coord.output_count + 1):
        if coord.is_shutter_mode and output in (SHUTTER_UP_CHANNEL, SHUTTER_DOWN_CHANNEL):
            # While the device runs in shutter mode these two channels drive
            # the motor and are represented by the cover entity instead.
            continue
        entities.append(EisusOutputSwitch(coord, output))

    if coord.supports("pulse"):
        for output in range(1, coord.output_count + 1):
            entities.append(EisusPulseSwitch(coord, output))

    if coord.supports("childlock"):
        entities.append(EisusChildLockSwitch(coord))

    async_add_entities(entities)


class EisusOutputSwitch(EisusEntity, SwitchEntity):
    """One relay output of the device."""

    _attr_should_poll = False

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_output{output}"
        self._attr_name = f"Output {output}"

    @property
    def is_on(self) -> bool:
        return self.pbool(f"output{self._output}")

    @property
    def extra_state_attributes(self):
        override = self.psub("manualOverride").get(f"output{self._output}")
        return {"manual_override": override}

    async def async_turn_on(self, **kwargs):
        await self.coord.async_set_output(self._output, True)

    async def async_turn_off(self, **kwargs):
        await self.coord.async_set_output(self._output, False)


class EisusPulseSwitch(EisusEntity, SwitchEntity):
    """Pulse / gate-opener mode of one output.

    When enabled, activating the output turns it off again automatically after
    the configured duration - exactly what a gate opener or doorbell needs.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, output: int):
        super().__init__(coord)
        self._output = output
        self._attr_unique_id = f"{self._did}_pulse{output}"
        self._attr_name = f"Output {output} pulse mode"

    @property
    def _cfg(self) -> dict:
        cfg = self.psub("pulse").get(f"output{self._output}")
        return cfg if isinstance(cfg, dict) else {}

    def _duration(self) -> int:
        try:
            value = int(self._cfg.get("durationMs") or 0)
        except (TypeError, ValueError):
            value = 0
        return value if value >= PULSE_MIN_DURATION_MS else PULSE_DEFAULT_DURATION_MS

    @property
    def is_on(self) -> bool:
        return bool(self._cfg.get("enabled"))

    @property
    def extra_state_attributes(self):
        return {"duration_ms": self._cfg.get("durationMs")}

    async def async_turn_on(self, **kwargs):
        await self.coord.async_set_pulse(self._output, True, self._duration())

    async def async_turn_off(self, **kwargs):
        await self.coord.async_set_pulse(self._output, False, self._duration())


class EisusChildLockSwitch(EisusEntity, SwitchEntity):
    """Child lock: blocks the physical wall switches on the device."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_childlock"
        self._attr_name = "Child lock"

    @property
    def is_on(self) -> bool:
        return self.pbool("childLock")

    async def async_turn_on(self, **kwargs):
        await self.coord.async_set_child_lock(True)

    async def async_turn_off(self, **kwargs):
        await self.coord.async_set_child_lock(False)
