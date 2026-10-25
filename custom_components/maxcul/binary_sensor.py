"""Binary sensor platform module of MaxCUL integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from maxcul._const import (
    ATTR_BATTERY_LOW,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_SERIAL,
    ATTR_DEVICE_TYPE,
)

from . import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_DEVICE_REPAIRED,
    SIGNAL_SHUTTER_UPDATE,
    SIGNAL_THERMOSTAT_UPDATE,
    MaxCulConfigEntry,
    MaxCulConnection,
    register_paired_device,
)
from .max_shutter import MaxShutter


def _normalize_device_label(device_type: str | None) -> str:
    """Convert a raw Max! device type into a readable label."""
    if not isinstance(device_type, str) or not device_type:
        return "Max device"

    normalized = device_type.replace("_", " ")
    words = [word for word in normalized.split() if word]
    if not words:
        return "Max device"

    return " ".join(word.capitalize() for word in words)


def _is_shutter_device_type(device_type: Any) -> bool:
    """Return True for Max! contact/window models supported by pymaxcul."""
    if not isinstance(device_type, str):
        return False
    upper_type = device_type.upper()
    return "SHUTTER" in upper_type or "WINDOW" in upper_type or "CONTACT" in upper_type


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MaxCulConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform for the MaxCUL integration."""

    device_path: str = config_entry.data[CONF_DEVICE_PATH]
    connection = config_entry.runtime_data

    known_devices = config_entry.data.get(CONF_DEVICES) or {}
    added_device_ids = set(known_devices)
    entities: list[BinarySensorEntity] = []
    for device_id, device in known_devices.items():
        entities.append(MaxBattery(connection, device_id, device[CONF_NAME]))
        if _is_shutter_device_type(device[CONF_TYPE]):
            entities.append(MaxShutter(connection, device_id, device[CONF_NAME]))

    async_add_entities(entities)

    @callback
    def paired_callback(payload: dict[str, Any]) -> None:
        if payload.get(ATTR_CONNECTION_DEVICE_PATH) != device_path:
            return

        raw_device_id = payload.get(ATTR_DEVICE_ID)
        if raw_device_id is None:
            return
        device_id = str(raw_device_id)
        if device_id in added_device_ids:
            return

        device_type = payload.get(ATTR_DEVICE_TYPE)
        if not isinstance(device_type, str):
            return
        added_device_ids.add(device_id)
        device_name = payload.get(ATTR_DEVICE_SERIAL)
        if not isinstance(device_name, str) or not device_name:
            device_name = _normalize_device_label(device_type)
        register_paired_device(
            hass, config_entry, device_id, device_name, device_type
        )
        devices_to_add: list[BinarySensorEntity] = [
            MaxBattery(connection, device_id, device_name)
        ]

        if _is_shutter_device_type(device_type):
            devices_to_add.append(MaxShutter(connection, device_id, device_name))

        async_add_entities(devices_to_add)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, paired_callback)
    )
    config_entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, paired_callback)
    )


class MaxBattery(BinarySensorEntity):
    """Battery sensor entity for Max devices."""

    _attr_has_entity_name = True
    _attr_translation_key = "battery"
    _attr_icon = "mdi:battery"

    def __init__(
        self, connection: MaxCulConnection, device_id: str, name: str
    ) -> None:
        self._name = name
        self._device_id = device_id
        self._connection = connection
        self._battery_low: bool | None = None

        self._connection.add_paired_device(self.sender_id)

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._name,
            "manufacturer": "eQ-3 / MAX!",
            "configuration_url": "https://github.com/powerpaul17/maxcul",
        }

    async def async_added_to_hass(self) -> None:
        """Register update listeners when the entity is added."""

        @callback
        def update(payload: dict[str, Any]) -> None:
            if payload.get(ATTR_DEVICE_ID) != self.sender_id:
                return

            self._battery_low = payload.get(ATTR_BATTERY_LOW)
            self.async_schedule_update_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_THERMOSTAT_UPDATE, update)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SHUTTER_UPDATE, update)
        )

    @property
    def unique_id(self) -> str:
        return f"{self._device_id}-battery"

    @property
    def sender_id(self) -> int:
        """Return the device RF address."""
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        return BinarySensorDeviceClass.BATTERY

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        return self._battery_low
