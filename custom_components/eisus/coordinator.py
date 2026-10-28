"""Local HTTP coordinator for EISUS devices (firmware v9.6.6+).

Every request goes to the device's own WebServer on TCP/80 and carries the
X-Local-Token header.  There is no broker, no cloud round-trip and no MQTT in
this path, so control keeps working while the device is offline from the
cloud - and vice versa.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta

import aiohttp
from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo

from .const import (
    CMD_RETRIES,
    CONF_HOST,
    CONF_INFO,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
    HEADER_TOKEN,
    HTTP_TIMEOUT_S,
    INFO_REFRESH_S,
    MDNS_QUERY_TIMEOUT_MS,
    MDNS_REDISCOVER_MIN_INTERVAL_S,
    MDNS_SERVICE,
    PATH_CMD,
    PATH_INFO,
    PATH_STATE,
    PATH_TIMER,
    PATH_TIME_GET,
    SCAN_INTERVAL_S,
    TIME_SYNC_MIN_INTERVAL_S,
)
from .device_registry import DeviceHandler, resolve_handler

_LOGGER = logging.getLogger(__name__)


class EisusCoordinator(DataUpdateCoordinator):
    """Poll /local/state and push every command to the device over HTTP."""

    def __init__(self, hass, entry):
        interval = timedelta(seconds=SCAN_INTERVAL_S)
        try:
            super().__init__(
                hass, _LOGGER, name=DOMAIN, update_interval=interval, config_entry=entry
            )
        except TypeError:
            # Home Assistant < 2024.2 does not accept config_entry here.
            super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=interval)

        self.entry = entry
        if getattr(self, "config_entry", None) is None:
            try:
                self.config_entry = entry
            except AttributeError:
                pass

        self.host = entry.data[CONF_HOST]
        self.port = int(entry.data.get(CONF_PORT, DEFAULT_PORT))
        self.token = entry.data[CONF_TOKEN]
        self.session = async_get_clientsession(hass)
        self.info = dict(entry.data.get(CONF_INFO) or {})
        self._instance = self._mdns_instance(self.info.get("deviceId"))
        self._last_rediscover = 0.0
        self._switch_mode = None
        # Device type registry: decides the platform set, the capabilities and
        # the command mapping for this device (see device_registry.py).
        self.handler: DeviceHandler = resolve_handler(self.info, None)
        self._last_info_fetch = 0.0
        self._last_time_sync = 0.0
        # Cleared when the firmware answers 404 for /local/time/* (pre-FIX-82).
        self.supports_time_endpoints = True

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _mdns_instance(device_id) -> str:
        """Mirror localMdnsAdvertise(): 'eisus-<devid>' with non-alnum -> '-'."""
        did = str(device_id or "").lower()
        return "eisus-" + re.sub(r"[^a-z0-9]", "-", did)

    @property
    def _headers(self) -> dict:
        return {HEADER_TOKEN: self.token}

    @property
    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    @property
    def device_key(self) -> str:
        return self.info.get("deviceId") or self.entry.entry_id

    @property
    def state_view(self) -> dict:
        """Normalised view of the last /local/state document (registry)."""
        return self.handler.parse_state(self.data or {})

    def supports(self, feature: str) -> bool:
        """Ask the device type registry whether the device has `feature`."""
        return self.handler.supports(feature)

    @property
    def device_type(self) -> str:
        return self.handler.device_type

    @property
    def output_count(self) -> int:
        """Relay channel count: /local/info's outputCount, else state keys.

        Gang detection for 1/2/3/4 gang modules lives in the registry handler
        (device_registry.DeviceHandler.output_count).
        """
        return self.handler.output_count

    @property
    def switch_mode(self) -> int:
        try:
            return int((self.data or {}).get("switchMode", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def is_shutter_mode(self) -> bool:
        """True when this device drives a shutter (subtype or switchMode 2)."""
        return self.handler.is_shutter

    # ------------------------------------------------------------- mDNS / net

    async def async_rediscover(self) -> bool:
        """Re-resolve the device through mDNS; True when the address changed.

        Called whenever a request fails, which covers the "DHCP handed the
        device a new IP" case without the user having to reconfigure anything.
        """
        now = self.hass.loop.time()
        if now - self._last_rediscover < MDNS_REDISCOVER_MIN_INTERVAL_S:
            return False
        self._last_rediscover = now
        try:
            zc = await ha_zeroconf.async_get_async_instance(self.hass)
            info = AsyncServiceInfo(MDNS_SERVICE, f"{self._instance}.{MDNS_SERVICE}")
            if not await info.async_request(zc.zeroconf, MDNS_QUERY_TIMEOUT_MS):
                return False
        except Exception as err:  # noqa: BLE001 - discovery must never break polling
            _LOGGER.debug("EISUS mDNS lookup failed: %s", err)
            return False

        addrs = info.parsed_addresses(IPVersion.V4Only)
        if not addrs:
            return False
        host = addrs[0]
        port = int(info.port or DEFAULT_PORT)
        if host == self.host and port == self.port:
            return False

        _LOGGER.warning(
            "EISUS device moved: %s:%s -> %s:%s", self.host, self.port, host, port
        )
        self.host = host
        self.port = port
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_HOST: host, CONF_PORT: port}
        )
        return True

    async def _request(self, method: str, path: str, payload=None):
        """One HTTP round-trip with retries and transparent re-discovery."""
        last_err = None
        for attempt in range(CMD_RETRIES):
            try:
                if method == "GET":
                    request = self.session.get(
                        self._url(path), headers=self._headers, timeout=self._timeout
                    )
                else:
                    request = self.session.post(
                        self._url(path),
                        json=payload,
                        headers=self._headers,
                        timeout=self._timeout,
                    )
                async with request as resp:
                    if resp.status == 401:
                        raise UpdateFailed("device rejected the local token (401)")
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    # 503 = the device state mutex was busy, worth a retry.
                    last_err = UpdateFailed(f"http {resp.status}")
            except UpdateFailed:
                raise
            except Exception as err:  # noqa: BLE001
                last_err = err
            if attempt == 0:
                await self.async_rediscover()
            await asyncio.sleep(0.3)
        raise UpdateFailed(str(last_err) if last_err else "request failed")

    # ----------------------------------------------------------------- polling

    async def async_fetch_info(self) -> dict:
        """GET /local/info and cache the result in the config entry."""
        info = await self._request("GET", PATH_INFO)
        if not isinstance(info, dict) or not info.get("deviceId"):
            raise UpdateFailed("unexpected /local/info payload")
        self.info = info
        self._instance = self._mdns_instance(info.get("deviceId"))
        self._last_info_fetch = self.hass.loop.time()
        # Keep the device-type handler in sync with the reported identity.
        self.handler.update(info=info, state=self.data)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_INFO: info}
        )
        return info

    def _track_switch_mode(self, state: dict) -> None:
        """Reload the entry when the device changes switch mode.

        Toggle/momentary and shutter expose a different entity set (four
        switches vs. one cover), so the platform setup has to run again.
        """
        mode = state.get("switchMode")
        if mode is None:
            return
        try:
            mode = int(mode)
        except (TypeError, ValueError):
            return
        if self._switch_mode is None or mode == self._switch_mode:
            self._switch_mode = mode
            return
        _LOGGER.info(
            "EISUS switch mode changed %s -> %s; reloading to re-map entities",
            self._switch_mode,
            mode,
        )
        self._switch_mode = mode
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def _async_update_data(self) -> dict:
        try:
            state = await self._request("GET", PATH_STATE)
        except UpdateFailed:
            if not await self.async_rediscover():
                raise
            state = await self._request("GET", PATH_STATE)
        if not isinstance(state, dict):
            raise UpdateFailed("unexpected /local/state payload")
        self._track_switch_mode(state)
        # Feed the device-type handler (registry) with the fresh documents: it
        # decides what the entities see and what the services may send.
        self.handler.update(state=state)
        await self._maybe_refresh_info()
        await self._maybe_sync_time(state)
        return state

    async def _maybe_refresh_info(self) -> None:
        """Re-read /local/info periodically (RSSI, capabilities, cloud state)."""
        now = self.hass.loop.time()
        if now - self._last_info_fetch < INFO_REFRESH_S:
            return
        self._last_info_fetch = now
        try:
            await self.async_fetch_info()
        except Exception as err:  # noqa: BLE001 - diagnostics never break polling
            _LOGGER.debug("EISUS /local/info refresh failed: %s", err)

    async def _maybe_sync_time(self, state: dict) -> None:
        """Give the device a clock when it has none (LAN-only install).

        The device syncs its clock over NTP, which needs internet - exactly
        what a local-only (or cloud-outage) install does not have. Home
        Assistant is the time source in that case, otherwise schedules and
        timers would never fire. Runs at most once per TIME_SYNC_MIN_INTERVAL_S.
        """
        if not self.handler.supports("time"):
            return
        clock = state.get("time")
        if isinstance(clock, dict) and clock.get("valid"):
            return
        now = self.hass.loop.time()
        if now - self._last_time_sync < TIME_SYNC_MIN_INTERVAL_S:
            return
        self._last_time_sync = now
        try:
            await self.async_set_time()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("EISUS time sync failed: %s", err)

    # ---------------------------------------------------------------- commands

    async def _post(self, path: str, payload: dict):
        """POST a payload, fold the returned state back in, return the ack."""
        data = await self._request("POST", path, payload)
        if isinstance(data, dict):
            ack = data.get("ack")
            if isinstance(ack, dict) and ack.get("status") == "error":
                _LOGGER.warning(
                    "EISUS rejected '%s' (%s): %s",
                    ack.get("command"),
                    ack.get("at"),
                    ack.get("reason"),
                )
            state = data.get("state")
            if isinstance(state, dict):
                self._track_switch_mode(state)
                self.async_set_updated_data(state)
                return ack
        await self.async_request_refresh()
        return None

    async def async_post(self, path: str, payload: dict):
        """Raw escape hatch used by the eisus.send_command service."""
        return await self._post(path, payload)

    async def async_action(self, action: str, **kwargs):
        """Run a logical action through the device-type registry.

        Every command this integration sends is mapped by
        device_registry.DeviceHandler.build_command(), so supporting a new
        device type means describing its commands in the registry only.
        """
        path, payload = self.handler.build_command(action, **kwargs)
        return await self._post(path, payload)

    async def async_cmd(self, payload: dict):
        """Raw /local/cmd payload (escape hatch for keys without an entity)."""
        return await self._post(PATH_CMD, payload)

    # ---- outputs and configuration (switch devices) -----------------------

    async def async_set_output(self, output: int, on: bool):
        return await self.async_action("output", output=int(output), on=bool(on))

    async def async_set_switch_mode(self, mode: int):
        return await self.async_action("switch_mode", mode=int(mode))

    async def async_set_power_restore(self, mode: int):
        return await self.async_action("power_restore", mode=int(mode))

    async def async_set_child_lock(self, locked: bool):
        return await self.async_action("child_lock", locked=bool(locked))

    async def async_set_pulse(self, output, enabled: bool, duration_ms: int):
        """Pulse / gate-opener mode. output=None applies to every output."""
        return await self.async_action(
            "pulse",
            output=output,
            enabled=bool(enabled),
            duration_ms=int(duration_ms),
        )

    # ---- shutter ----------------------------------------------------------

    async def async_shutter(self, action: str):
        return await self.async_action("shutter", shutter_action=str(action))

    async def async_set_shutter_position(self, position: int):
        return await self.async_action("shutter_position", position=int(position))

    async def async_set_shutter_travel(self, open_ms: int, close_ms: int):
        """Direct calibration: store both travel times, mark as calibrated."""
        return await self.async_action(
            "shutter_calibrate", open_time_ms=int(open_ms), close_time_ms=int(close_ms)
        )

    async def async_shutter_calibrate(self, mode=None, action=None):
        """Interactive calibration sequence: start -> open/stop/close -> end."""
        return await self.async_action(
            "shutter_calibrate", mode=mode, calibration_action=action
        )

    async def async_timer_set(
        self,
        output: int,
        state: bool,
        duration_ms: int,
        after_ms: int = 0,
        restore_state: bool = True,
    ):
        return await self._post(
            PATH_TIMER,
            {
                "output": int(output),
                "state": bool(state),
                "durationMs": int(duration_ms),
                "afterMs": int(after_ms),
                "restoreState": bool(restore_state),
            },
        )

    # ---- timers -----------------------------------------------------------

    async def async_timer_cancel(self, output: int):
        return await self.async_action("timer_cancel", output=int(output))

    async def async_timer_get(self):
        """Ask the device for its timer table ({"command": "get"})."""
        return await self._post(PATH_TIMER, {"command": "get"})

    async def async_timer_cancel_all(self):
        """Cancel whatever timer/pulse runs on each output, in turn."""
        result = None
        for output in range(1, self.output_count + 1):
            result = await self.async_timer_cancel(output)
        return result

    # ---- weekly schedule --------------------------------------------------

    async def async_schedule(self, payload: dict):
        return await self.async_action("schedule", payload=payload)

    async def async_schedule_set(self, rules):
        """Replace every weekly rule: {"command": "set", "rules": [...]}."""
        return await self.async_schedule({"command": "set", "rules": list(rules)})

    async def async_schedule_get(self):
        return await self.async_schedule({"command": "get"})

    async def async_schedule_clear(self):
        return await self.async_schedule({"command": "clear"})

    # ---- clock (firmware FIX-82: /local/time/set + /local/time/get) --------

    def _local_time_payload(self) -> dict:
        """Home Assistant's own clock, expressed in its configured timezone."""
        moment = dt_util.now()
        offset = moment.utcoffset()
        return {
            "epoch": int(moment.timestamp()),
            "timezone": self.hass.config.time_zone,
            "offset_sec": int(offset.total_seconds()) if offset is not None else None,
        }

    async def async_set_time(self, epoch=None, timezone=None, offset_sec=None):
        """Set the device clock. Defaults to the Home Assistant clock.

        Falls back gracefully: if the firmware predates FIX-82 it answers 404,
        which disables further clock pushes instead of spamming the log.
        """
        values = self._local_time_payload()
        if epoch is not None:
            values["epoch"] = int(epoch)
        if timezone is not None:
            values["timezone"] = str(timezone)
        if offset_sec is not None:
            values["offset_sec"] = int(offset_sec)
        path, payload = self.handler.build_command("time_set", **values)
        try:
            return await self._post(path, payload)
        except UpdateFailed as err:
            if "404" in str(err):
                self.supports_time_endpoints = False
                _LOGGER.warning(
                    "EISUS %s: firmware does not implement %s (needs v9.6.6 / "
                    "FIX-82) - the device clock cannot be set from Home Assistant",
                    self.device_key,
                    path,
                )
            raise

    async def async_get_time(self) -> dict:
        """Read the device clock; falls back to the /local/state time block."""
        if self.supports_time_endpoints:
            try:
                data = await self._request("GET", PATH_TIME_GET)
                if isinstance(data, dict):
                    return data
            except UpdateFailed as err:
                if "404" in str(err):
                    self.supports_time_endpoints = False
                    _LOGGER.info(
                        "EISUS %s: /local/time/get is not available; using "
                        "/local/state for the device clock",
                        self.device_key,
                    )
                elif "401" not in str(err):
                    raise
        clock = (self.data or {}).get("time")
        return clock if isinstance(clock, dict) else {}

    # ---- maintenance ------------------------------------------------------

    async def async_factory_reset(self):
        return await self.async_action("factory_reset")


def coordinator_by_device_key(hass, device_key):
    """Find the coordinator whose deviceId matches `device_key`."""
    for coord in (hass.data.get(DOMAIN) or {}).values():
        if coord.device_key == device_key:
            return coord
    return None


def coordinator_for_ha_device(hass, ha_device_id):
    """Resolve a Home Assistant device-registry id to an EISUS coordinator.

    Service calls address Home Assistant devices, not deviceIds, so the device
    registry is queried for the (DOMAIN, deviceId) identifier first.
    """
    from homeassistant.helpers.device_registry import async_get as async_get_dr

    device = async_get_dr(hass).async_get(ha_device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain != DOMAIN:
            continue
        coord = coordinator_by_device_key(hass, ident)
        if coord is not None:
            return coord
    return None


