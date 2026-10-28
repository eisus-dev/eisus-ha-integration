"""Weekly schedule helpers and the ``eisus.set_schedule`` service.

Home Assistant has no native "weekly rule" entity and the firmware stores its
rules as a single JSON array, so schedules are managed through a service.  This
module owns the rule schema, validates/normalises user input and registers the
service; everything else (auth, retries, IP changes) is the coordinator's job.

Firmware rule schema (see mqttHandleSchedule / scheduleRuleFromJson):

    {
      "id": 1,                          # unique rule id (int >= 1)
      "enabled": true,
      "days": 62,                       # bit0=Sunday .. bit6=Saturday
      "startMin": 420,                  # minutes after local midnight
      "endMin": 1380,
      "scheduleid": "morning",          # optional correlation id
      "outputs": {"output1": true, "output2": false}
    }

The service accepts a friendlier form and converts it:

    - days:      [mon, tue, wed] | "mon,tue" | [monday] | 62   (bitmask)
    - start/end: "07:00" | 420                                 (minutes)
    - outputs:   {1: true} | {output1: true} | [1, 2]
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_RULES,
    DAY_BITS,
    DOMAIN,
    MAX_SCHEDULE_RULES,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import coordinator_for_ha_device

_LOGGER = logging.getLogger(__name__)

# Long weekday names are accepted as a convenience (["monday"] == ["mon"]).
DAY_LONG = {
    "sunday": "sun",
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
}

SERVICE_SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_RULES, default=list): vol.All(cv.ensure_list, [dict]),
    }
)


def days_to_mask(days) -> int:
    """Convert a weekday list/string (or a raw bitmask) to the firmware mask."""
    if isinstance(days, int):
        return max(0, min(127, days))
    if isinstance(days, str):
        days = [part for part in days.replace(",", " ").split() if part]
    mask = 0
    for day in days or []:
        raw = str(day).strip().lower()
        key = DAY_LONG.get(raw)
        if key is None and raw in DAY_BITS:
            key = raw
        if key is None:
            raise ValueError(
                f"unknown weekday '{day}' (use sun..sat or sunday..saturday)"
            )
        mask |= DAY_BITS[key]
    if mask == 0:
        raise ValueError("'days' must select at least one weekday")
    return mask


def minutes_of_day(value, field: str) -> int:
    """Accept 420 or "07:00" (or "07:00:00") and return minutes past midnight."""
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        total = hours * 60 + minutes
    else:
        total = int(value)
    if not 0 <= total <= 1440:
        raise ValueError(f"'{field}' must be between 00:00 and 24:00 (0..1440)")
    return total


def normalize_outputs(outputs) -> dict:
    """Accept {1: True}, {output1: True} or [1, 2] and return outputN keys."""
    normalized = {}
    if isinstance(outputs, (list, tuple, set)):
        for item in outputs:
            normalized[f"output{int(item)}"] = True
        return normalized
    if isinstance(outputs, dict):
        for key, value in outputs.items():
            name = str(key).strip().lower()
            if name.isdigit():
                name = f"output{name}"
            if not name.startswith("output") or not name[6:].isdigit():
                raise ValueError(
                    f"unknown output key '{key}' (use output1..output4 or 1..4)"
                )
            normalized[name] = bool(value)
        return normalized
    if outputs is None:
        return normalized
    raise ValueError("'outputs' must be a mapping or a list of output numbers")


def normalize_rule(rule: dict, index: int) -> dict:
    """Validate one rule and translate it to the firmware's key names."""
    if not isinstance(rule, dict):
        raise ValueError("every rule must be a mapping")
    start = rule.get("startMin", rule.get("start_min", rule.get("start")))
    end = rule.get("endMin", rule.get("end_min", rule.get("end")))
    if start is None or end is None:
        raise ValueError("every rule needs 'start' and 'end' (or startMin/endMin)")
    normalized = {
        "id": int(rule.get("id", index)),
        "enabled": bool(rule.get("enabled", True)),
        "days": days_to_mask(rule.get("days")),
        "startMin": minutes_of_day(start, "start"),
        "endMin": minutes_of_day(end, "end"),
    }
    schedule_id = rule.get("scheduleid", rule.get("schedule_id"))
    if schedule_id:
        normalized["scheduleid"] = str(schedule_id)
    if rule.get("outputs") is not None:
        outputs = normalize_outputs(rule.get("outputs"))
        if outputs:
            normalized["outputs"] = outputs
    return normalized


def normalize_rules(rules) -> list:
    """Validate a whole rule list (this is what replaces the device's rules)."""
    rules = list(rules or [])
    if len(rules) > MAX_SCHEDULE_RULES:
        raise ValueError(
            f"the device stores at most {MAX_SCHEDULE_RULES} rules "
            f"({len(rules)} given)"
        )
    return [normalize_rule(rule, index) for index, rule in enumerate(rules, start=1)]


def async_register_services(hass: HomeAssistant) -> None:
    """Register ``eisus.set_schedule`` (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        return

    async def _handle_set_schedule(call: ServiceCall) -> None:
        coord = coordinator_for_ha_device(hass, call.data[ATTR_DEVICE_ID])
        if coord is None:
            raise HomeAssistantError(
                f"EISUS device {call.data[ATTR_DEVICE_ID]} is not configured"
            )
        try:
            rules = normalize_rules(call.data.get(ATTR_RULES))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(f"invalid schedule rule: {err}") from err

        _LOGGER.debug(
            "EISUS %s: uploading %d schedule rule(s)", coord.device_key, len(rules)
        )
        await coord.async_schedule_set(rules)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        _handle_set_schedule,
        schema=SERVICE_SET_SCHEDULE_SCHEMA,
    )
