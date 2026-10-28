"""Configuration selects for EISUS devices."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN, POWER_RESTORE_MODES, SWITCH_MODES
from .entity import EisusEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data[DOMAIN][entry.entry_id]
    if coord.device_type != "switch":
        return
    entities = []
    if coord.supports("switchmode"):
        entities.append(EisusSwitchModeSelect(coord))
    if coord.supports("powerrestore"):
        entities.append(EisusPowerRestoreSelect(coord))
    async_add_entities(entities)


class EisusSelectEntity(EisusEntity, SelectEntity):
    """Common plumbing for the firmware's integer-valued enumerations."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def _modes(self) -> dict:
        raise NotImplementedError

    def _current_key(self):
        raise NotImplementedError

    async def _apply(self, key: int) -> None:
        raise NotImplementedError

    @property
    def options(self) -> list:
        return list(self._modes().values())

    @property
    def current_option(self):
        return self._modes().get(self._current_key())

    async def async_select_option(self, option: str) -> None:
        for key, label in self._modes().items():
            if label == option:
                await self._apply(key)
                return


class EisusSwitchModeSelect(EisusSelectEntity):
    """How the physical wall switches behave: toggle / momentary / shutter."""

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_switchmode"
        self._attr_name = "Switch mode"

    def _modes(self) -> dict:
        return SWITCH_MODES

    def _current_key(self):
        return self.pint("switchMode")

    async def _apply(self, key: int) -> None:
        await self.coord.async_set_switch_mode(key)


class EisusPowerRestoreSelect(EisusSelectEntity):
    """Relay state the device restores after a power cut."""

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = f"{self._did}_powerrestore"
        self._attr_name = "Power restore"

    def _modes(self) -> dict:
        return POWER_RESTORE_MODES

    def _current_key(self):
        return self.pint("powerRestore")

    async def _apply(self, key: int) -> None:
        await self.coord.async_set_power_restore(key)
