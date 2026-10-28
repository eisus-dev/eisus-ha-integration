"""Config flow for the EISUS integration (mDNS discovery + manual setup)."""

from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HOST,
    CONF_INFO,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
    HEADER_TOKEN,
    HTTP_TIMEOUT_S,
    PATH_INFO,
)

_LOGGER = logging.getLogger(__name__)


def _zc_attr(discovery_info, name):
    """Read an attribute from a dict or an object (ZeroconfServiceInfo)."""
    if isinstance(discovery_info, dict):
        return discovery_info.get(name)
    return getattr(discovery_info, name, None)


def _prop(props, key):
    """Read one mDNS TXT property, tolerating bytes and empty values."""
    value = props.get(key)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode(errors="ignore")
    if value is None or value == "":
        return None
    return value


async def _probe(hass, host, port, token):
    """Return the /local/info document, or an error key string."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"http://{host}:{port}{PATH_INFO}",
            headers={HEADER_TOKEN: token},
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
        ) as resp:
            if resp.status == 401:
                return "invalid_auth"
            if resp.status != 200:
                return "cannot_connect"
            info = await resp.json(content_type=None)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("EISUS probe %s:%s failed: %s", host, port, err)
        return "cannot_connect"
    if not isinstance(info, dict) or not info.get("deviceId"):
        return "cannot_connect"
    return info


class EisusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle mDNS discovery and manual configuration."""

    VERSION = 1

    def __init__(self):
        self._host = None
        self._port = DEFAULT_PORT
        self._discovered = {}

    async def async_step_zeroconf(self, discovery_info):
        """Handle a device announced over _eisus._tcp."""
        host = _zc_attr(discovery_info, "ip_address")
        if not host:
            addresses = _zc_attr(discovery_info, "ip_addresses") or []
            host = addresses[0] if addresses else None
        if not host:
            return self.async_abort(reason="cannot_connect")

        self._host = str(host)
        self._port = _zc_attr(discovery_info, "port") or DEFAULT_PORT

        props = _zc_attr(discovery_info, "properties") or {}
        devid = _prop(props, "devid")
        if devid:
            self._discovered = {
                "deviceId": devid,
                "type": _prop(props, "type"),
                "subtype": _prop(props, "sub"),
                "fwVersion": _prop(props, "fw"),
                "hwVersion": _prop(props, "hw"),
                "mac": _prop(props, "mac"),
            }
            # FIX-82 firmware advertises the gang count as "out" (1..4).
            outputs = _prop(props, "out")
            if outputs and str(outputs).isdigit():
                self._discovered["outputCount"] = int(outputs)
            await self.async_set_unique_id(devid)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )

        self.context["title_placeholders"] = {
            "name": devid or f"{self._host}:{self._port}"
        }
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            host = user_input[CONF_HOST].strip()
            try:
                port = int(user_input.get(CONF_PORT) or DEFAULT_PORT)
            except (TypeError, ValueError):
                port = DEFAULT_PORT
            token = user_input[CONF_TOKEN].strip()

            result = await _probe(self.hass, host, port, token)
            if isinstance(result, str):
                errors["base"] = result
            else:
                info = result
                await self.async_set_unique_id(info["deviceId"])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port, CONF_TOKEN: token}
                )
                return self.async_create_entry(
                    title=info.get("name") or f"EISUS {str(info['deviceId'])[:8]}",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_TOKEN: token,
                        CONF_INFO: info,
                    },
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._host or ""): str,
                    vol.Optional(CONF_PORT, default=self._port or DEFAULT_PORT): int,
                    vol.Required(CONF_TOKEN): str,
                }
            ),
            description_placeholders={"device": self._host or ""},
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Re-enter the local token when the device rejects the stored one."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input:
            token = user_input[CONF_TOKEN].strip()
            result = await _probe(
                self.hass,
                entry.data[CONF_HOST],
                entry.data.get(CONF_PORT, DEFAULT_PORT),
                token,
            )
            if isinstance(result, str):
                errors["base"] = result
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_TOKEN: token, CONF_INFO: result}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return EisusOptionsFlow(config_entry)


class EisusOptionsFlow(config_entries.OptionsFlow):
    """Allow host / port / token to be corrected after setup."""

    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input:
            host = user_input[CONF_HOST].strip()
            try:
                port = int(user_input.get(CONF_PORT) or DEFAULT_PORT)
            except (TypeError, ValueError):
                port = DEFAULT_PORT
            token = user_input[CONF_TOKEN].strip()
            result = await _probe(self.hass, host, port, token)
            if isinstance(result, str):
                errors["base"] = result
            else:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **self._entry.data,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_TOKEN: token,
                        CONF_INFO: result,
                    },
                )
                await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=self._entry.data.get(CONF_HOST, "")
                    ): str,
                    vol.Optional(
                        CONF_PORT,
                        default=self._entry.data.get(CONF_PORT, DEFAULT_PORT),
                    ): int,
                    vol.Required(
                        CONF_TOKEN, default=self._entry.data.get(CONF_TOKEN, "")
                    ): str,
                }
            ),
        )

