"""Climate platform module of MaxCUL integration."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_DEVICE_SERIAL,
    ATTR_DEVICE_TYPE,
    HEATING_THERMOSTAT,
)

from . import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_DEVICE_PATH,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_DEVICE_REPAIRED,
    SIGNAL_WEEK_PROFILE_UPDATE,
    CONF_WEEK_PROFILES,
    MaxCulConfigEntry,
    register_paired_device,
)
from .max_thermostat import MaxThermostat
from .max_wall_thermostat import MaxWallThermostat


def _is_thermostat_device_type(device_type: Any) -> bool:
    """Return True for all Max! thermostat models supported by pymaxcul."""
    if not isinstance(device_type, str):
        return False
    upper_type = device_type.upper()
    return "THERMOSTAT" in upper_type or upper_type == HEATING_THERMOSTAT.upper()


def _normalize_device_label(device_type: str | None) -> str:
    """Convert a raw Max! device type into a readable label."""
    if not isinstance(device_type, str) or not device_type:
        return "Max device"

    normalized = device_type.replace("_", " ")
    words = [word for word in normalized.split() if word]
    if not words:
        return "Max device"

    return " ".join(word.capitalize() for word in words)


def _create_thermostat_entity(
    device_type: str,
    connection,
    device_id: str,
    name: str,
    device_path: str,
    profile_state: dict[str, Any] | None = None,
):
    """Create the correct entity for the matched Max! thermostat model."""
    upper_type = device_type.upper() if isinstance(device_type, str) else ""
    if "WALL" in upper_type or "PLUS" in upper_type:
        return MaxWallThermostat(
            connection, device_id, name, device_path, profile_state
        )
    return MaxThermostat(connection, device_id, name, device_path, profile_state)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MaxCulConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform for the MaxCUL integration from a config entry."""

    device_path: str = config_entry.data[CONF_DEVICE_PATH]
    connection = config_entry.runtime_data

    known_devices = config_entry.data.get(CONF_DEVICES) or {}
    profile_states = config_entry.data.get(CONF_WEEK_PROFILES) or {}
    added_device_ids = set(known_devices)

    async_add_entities(
        [
            _create_thermostat_entity(
                device[CONF_TYPE],
                connection,
                device_id,
                device[CONF_NAME],
                config_entry.data[CONF_DEVICE_PATH],
                profile_states.get(device_id),
            )
            for device_id, device in known_devices.items()
            if _is_thermostat_device_type(device[CONF_TYPE])
        ]
    )

    @callback
    def paired_callback(payload: dict[str, Any]) -> None:
        if payload.get(ATTR_CONNECTION_DEVICE_PATH) != device_path:
            return

        device_type = payload.get(ATTR_DEVICE_TYPE)
        if not _is_thermostat_device_type(device_type):
            return

        raw_device_id = payload.get(ATTR_DEVICE_ID)
        if raw_device_id is None:
            return
        device_id = str(raw_device_id)
        if device_id in added_device_ids:
            return
        added_device_ids.add(device_id)

        device_name = payload.get(ATTR_DEVICE_SERIAL)
        if not isinstance(device_name, str) or not device_name:
            device_name = _normalize_device_label(device_type)
        register_paired_device(
            hass, config_entry, device_id, device_name, device_type
        )

        async_add_entities(
            [
                _create_thermostat_entity(
                    device_type,
                    connection,
                    device_id,
                    device_name,
                    device_path,
                )
            ]
        )

    # async_on_unload removes the listeners when the entry is unloaded or reloaded.
    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, paired_callback)
    )
    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, paired_callback)
    )
