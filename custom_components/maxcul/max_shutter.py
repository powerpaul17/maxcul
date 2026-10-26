"""Binary sensor entity for Max window shutter contacts."""

from __future__ import annotations

from typing import Any, Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import ATTR_STATE
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from maxcul._const import ATTR_DEVICE_ID, SHUTTER_OPEN

from . import DOMAIN, SIGNAL_SHUTTER_UPDATE, MaxCulConnection


class MaxShutter(BinarySensorEntity):
    """Binary sensor entity for Max window shutter contacts."""

    _attr_has_entity_name = True

    @property
    def icon(self) -> str:
        return "mdi:window-open-variant" if self.is_on else "mdi:window-closed-variant"

    def __init__(
        self,
        connection: MaxCulConnection,
        device_id: str,
        name: str,
    ) -> None:
        self._name = name
        self._device_id = device_id
        self._connection = connection
        self._is_open: str | None = None

        self._connection.add_paired_device(self.sender_id)

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self.name,
            "manufacturer": "eQ-3 / MAX!",
            "model": "Window Contact",
            "configuration_url": "https://github.com/powerpaul17/maxcul",
        }

    async def async_added_to_hass(self) -> None:
        """Register the shutter update listener."""

        @callback
        def update(payload: dict[str, Any]) -> None:
            if payload.get(ATTR_DEVICE_ID) != self.sender_id:
                return

            self._is_open = payload.get(ATTR_STATE)
            self.async_schedule_update_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SHUTTER_UPDATE, update)
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def sender_id(self) -> int:
        """Return the RF address of the device."""
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        return BinarySensorDeviceClass.WINDOW

    @property
    def is_on(self) -> bool | None:
        if self._is_open is None:
            return None
        return self._is_open == SHUTTER_OPEN

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {}
