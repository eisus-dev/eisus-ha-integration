"""Shared base entity for the EISUS integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER


class EisusEntity(CoordinatorEntity):
    """Base class holding the shared device registry entry.

    Availability is inherited from CoordinatorEntity, so every entity in the
    integration goes unavailable the moment the device stops answering on the
    LAN instead of silently restoring the last known state.
    """

    _attr_has_entity_name = True

    def __init__(self, coord):
        super().__init__(coord)
        self.coord = coord
        info = coord.info or {}
        did = info.get("deviceId") or coord.entry.entry_id
        self._did = did
        model = info.get("type") or "switch"
        if info.get("subtype"):
            model = f"{model}/{info['subtype']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, did)},
            manufacturer=MANUFACTURER,
            name=info.get("name") or f"EISUS {str(did)[:8]}",
            model=model,
            sw_version=info.get("fwVersion"),
            hw_version=info.get("hwVersion"),
            configuration_url=f"http://{coord.host}:{coord.port}/",
        )

    @property
    def payload(self) -> dict:
        """Last /local/state document reported by the device."""
        return self.coord.data or {}

    def pbool(self, key: str, default: bool = False) -> bool:
        return bool(self.payload.get(key, default))

    def pint(self, key: str, default: int = 0) -> int:
        try:
            return int(self.payload.get(key, default))
        except (TypeError, ValueError):
            return default

    def psub(self, key: str) -> dict:
        value = self.payload.get(key)
        return value if isinstance(value, dict) else {}
