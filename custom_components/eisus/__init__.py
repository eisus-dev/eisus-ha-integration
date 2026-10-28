"""The EISUS integration: local HTTP control for EISUS Wi-Fi devices.

Firmware v9.6.6 removed the device-side Home Assistant MQTT client, so this
integration is the only Home Assistant side: it discovers devices over mDNS
(_eisus._tcp) and drives them through the token protected local HTTP API.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from . import schedule as eisus_schedule
from . import time as eisus_time
from .const import (
    ATTR_ACTION,
    ATTR_CLOSE_TIME_MS,
    ATTR_ENDPOINT,
    ATTR_MODE,
    ATTR_OPEN_TIME_MS,
    ATTR_OUTPUT,
    ATTR_PAYLOAD,
    DOMAIN,
    ENDPOINTS,
    MAX_OUTPUTS,
    SERVICE_CALIBRATE_SHUTTER,
    SERVICE_CANCEL_TIMER,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_TIME,
    SHUTTER_MAX_TRAVEL_MS,
    SHUTTER_MIN_TRAVEL_MS,
)
from .coordinator import EisusCoordinator, coordinator_for_ha_device
from .device_registry import ALL_PLATFORMS, platforms_for

_LOGGER = logging.getLogger(__name__)

# The entity platforms are chosen by the device-type registry
# (device_registry.py) from what /local/info reports, not hard-coded here.
PLATFORMS = list(ALL_PLATFORMS)


def _platforms_for(hass: HomeAssistant, entry: ConfigEntry) -> list:
    """Platforms to forward for this entry (device type + HA version aware)."""
    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    handler = getattr(coord, "handler", None)
    if handler is None:
        return list(PLATFORMS)
    available = PLATFORMS
    if not eisus_time.TIME_PLATFORM_AVAILABLE:
        # homeassistant.components.time does not exist before HA 2023.7.
        available = [p for p in PLATFORMS if p != "time"]
    return platforms_for(handler, available)

SERVICE_SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_ENDPOINT, default="cmd"): vol.In(list(ENDPOINTS)),
        vol.Required(ATTR_PAYLOAD): dict,
    }
)

SERVICE_CANCEL_TIMER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_OUTPUT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_OUTPUTS)
        ),
    }
)

SERVICE_CALIBRATE_SHUTTER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_MODE): vol.In(["start", "end"]),
        vol.Optional(ATTR_ACTION): vol.In(["open", "stop", "close"]),
        vol.Optional(ATTR_OPEN_TIME_MS): vol.All(
            vol.Coerce(int),
            vol.Range(min=SHUTTER_MIN_TRAVEL_MS, max=SHUTTER_MAX_TRAVEL_MS),
        ),
        vol.Optional(ATTR_CLOSE_TIME_MS): vol.All(
            vol.Coerce(int),
            vol.Range(min=SHUTTER_MIN_TRAVEL_MS, max=SHUTTER_MAX_TRAVEL_MS),
        ),
    }
)


def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> EisusCoordinator:
    """Map the Home Assistant device id in a service call to a coordinator."""
    coord = coordinator_for_ha_device(hass, call.data[ATTR_DEVICE_ID])
    if coord is None:
        raise HomeAssistantError(
            f"EISUS device {call.data[ATTR_DEVICE_ID]} is not configured"
        )
    return coord


def _register_service(hass: HomeAssistant) -> None:
    """Register eisus.send_command once, for payloads without an entity."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):
        return

    async def _handle_send_command(call: ServiceCall) -> None:
        target = _resolve_coordinator(hass, call)
        endpoint = call.data.get(ATTR_ENDPOINT, "cmd")
        await target.async_post(ENDPOINTS[endpoint], dict(call.data[ATTR_PAYLOAD]))

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        _handle_send_command,
        schema=SERVICE_SEND_COMMAND_SCHEMA,
    )


def _register_extra_services(hass: HomeAssistant) -> None:
    """eisus.cancel_timer / eisus.calibrate_shutter, plus the time and
    schedule modules' own services (eisus.set_time, eisus.set_schedule)."""
    eisus_time.async_register_services(hass)
    eisus_schedule.async_register_services(hass)

    if not hass.services.has_service(DOMAIN, SERVICE_CANCEL_TIMER):

        async def _handle_cancel_timer(call: ServiceCall) -> None:
            target = _resolve_coordinator(hass, call)
            output = call.data.get(ATTR_OUTPUT)
            if output:
                await target.async_timer_cancel(int(output))
            else:
                await target.async_timer_cancel_all()

        hass.services.async_register(
            DOMAIN,
            SERVICE_CANCEL_TIMER,
            _handle_cancel_timer,
            schema=SERVICE_CANCEL_TIMER_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CALIBRATE_SHUTTER):

        async def _handle_calibrate_shutter(call: ServiceCall) -> None:
            target = _resolve_coordinator(hass, call)
            open_ms = call.data.get(ATTR_OPEN_TIME_MS)
            close_ms = call.data.get(ATTR_CLOSE_TIME_MS)
            if open_ms is not None or close_ms is not None:
                # Direct calibration: the firmware takes both times as a pair,
                # so the missing one is filled from the device (or its minimum).
                shutter = (target.state_view.get("shutter") or {})
                await target.async_set_shutter_travel(
                    int(
                        open_ms
                        if open_ms is not None
                        else (shutter.get("open_time_ms") or SHUTTER_MIN_TRAVEL_MS)
                    ),
                    int(
                        close_ms
                        if close_ms is not None
                        else (shutter.get("close_time_ms") or SHUTTER_MIN_TRAVEL_MS)
                    ),
                )
                return
            await target.async_shutter_calibrate(
                mode=call.data.get(ATTR_MODE), action=call.data.get(ATTR_ACTION)
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_CALIBRATE_SHUTTER,
            _handle_calibrate_shutter,
            schema=SERVICE_CALIBRATE_SHUTTER_SCHEMA,
        )


def _unregister_services(hass: HomeAssistant) -> None:
    """Drop every eisus service once the last config entry is unloaded."""
    for service in (
        SERVICE_SEND_COMMAND,
        SERVICE_SET_TIME,
        SERVICE_SET_SCHEDULE,
        SERVICE_CANCEL_TIMER,
        SERVICE_CALIBRATE_SHUTTER,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coord = EisusCoordinator(hass, entry)
    try:
        # Identity, capabilities and device type: this is what the registry
        # turns into the entity set, so it runs before the platforms are set
        # up. A failure here is not fatal because the config entry already
        # caches the last known /local/info document.
        await coord.async_fetch_info()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("EISUS /local/info unavailable during setup: %s", err)

    # Raises ConfigEntryNotReady (and therefore retries later) when the device
    # is not reachable right now.
    await coord.async_config_entry_first_refresh()

    # Publish the coordinator before forwarding the platforms: the platform
    # modules look it up in hass.data[DOMAIN][entry.entry_id].
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    _register_service(hass)
    _register_extra_services(hass)

    platforms = _platforms_for(hass, entry)
    _LOGGER.debug(
        "EISUS %s: type=%s subtype=%s outputs=%s -> platforms %s",
        coord.device_key,
        coord.handler.device_type,
        coord.info.get("subtype"),
        coord.output_count,
        platforms,
    )
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, _platforms_for(hass, entry)
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            # Last device gone: take the eisus.* services with it.
            _unregister_services(hass)
    return unloaded
