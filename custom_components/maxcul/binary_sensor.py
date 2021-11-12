from typing import Any, Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    DEVICE_CLASS_WINDOW
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    ATTR_STATE,
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE
)

from homeassistant.core import (
    HomeAssistant,
    callback
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.maxcul import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_SHUTTER_UPDATE,
    MaxCulConnection
)

from custom_components.maxcul.pymaxcul.maxcul._const import (
    ATTR_BATTERY_LOW,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    SHUTTER_CONTACT
)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]
    devices = [
        MaxShutter(connection, device_id, device[CONF_NAME])
        for device_id, device in config_entry.data.get(CONF_DEVICES).items()
        if device[CONF_TYPE] == SHUTTER_CONTACT
    ]
    async_add_devices(devices)

    @callback
    def pairedCallback(payload):
        connection_device_path = payload.get(ATTR_CONNECTION_DEVICE_PATH)
        if connection_device_path is not device_path:
            return

        device_type = payload.get(ATTR_DEVICE_TYPE)
        if device_type is not SHUTTER_CONTACT:
            return

        device_id = payload.get(ATTR_DEVICE_ID)
        device_name = payload.get(ATTR_DEVICE_SERIAL)

        device = MaxShutter(connection, device_id, device_name)
        async_add_devices([device])

        new_data = {**config_entry.data}

        devices = new_data.get(CONF_DEVICES).copy()
        devices[device_id] = {
            CONF_NAME: device_name,
            CONF_TYPE: SHUTTER_CONTACT
        }

        new_data[CONF_DEVICES] = devices

        hass.config_entries.async_update_entry(config_entry, data=new_data)

    async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, pairedCallback)


class MaxShutter(BinarySensorEntity):

    def __init__(self, connection: MaxCulConnection, device_id, name):
        self._name = name
        self._device_id = device_id
        self._connection = connection

        self._is_open = None

        self._battery_low = None

        self._connection.add_paired_device(self._device_id)

    async def async_added_to_hass(self) -> None:
        @callback
        def update(payload):
            device_id = payload.get(ATTR_DEVICE_ID)
            if device_id != self._device_id:
                return

            self._is_open = payload.get(ATTR_STATE, None)

            self._battery_low = payload.get(ATTR_BATTERY_LOW, None)

            self.async_schedule_update_ha_state()

        async_dispatcher_connect(self.hass, SIGNAL_SHUTTER_UPDATE, update)

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_WINDOW

    @property
    def is_on(self) -> bool:
        return self._is_open

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {
            ATTR_BATTERY_LOW: self._battery_low
        }
