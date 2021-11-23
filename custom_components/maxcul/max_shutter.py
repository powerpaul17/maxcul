'''
Binary sensor entity module for Max window shutter sensors
'''

from typing import Any, Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    DEVICE_CLASS_WINDOW
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    ATTR_STATE
)

from homeassistant.core import (
    callback
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from maxcul._const import (
    ATTR_DEVICE_ID,
    SHUTTER_OPEN
)

from custom_components.maxcul import (
    DOMAIN,
    SIGNAL_SHUTTER_UPDATE,
    MaxCulConnection
)


class MaxShutter(BinarySensorEntity):
    ''' Binary sensor entity class for Max window shutter sensors '''

    def __init__(self, connection: MaxCulConnection, device_id, name):
        self._name = name
        self._device_id = device_id
        self._connection = connection

        self._is_open = None

        self._connection.add_paired_device(self.sender_id)

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {
                (DOMAIN, self._device_id)
            },
            "name": self.name,
        }

    async def async_added_to_hass(self) -> None:
        @callback
        def update(payload):
            device_id = payload.get(ATTR_DEVICE_ID)
            if device_id != self.sender_id:
                return

            self._is_open = payload.get(ATTR_STATE, None)

            self.async_schedule_update_ha_state()

        async_dispatcher_connect(self.hass, SIGNAL_SHUTTER_UPDATE, update)

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def sender_id(self) -> int:
        ''' Return the RF address of the device '''
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_WINDOW

    @property
    def is_on(self) -> bool:
        return self._is_open == SHUTTER_OPEN

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {}
