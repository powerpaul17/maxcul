from typing import Any, Mapping

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    DEVICE_CLASS_WINDOW,
    DEVICE_CLASS_BATTERY
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
from homeassistant.helpers.entity import DeviceInfo

from custom_components.maxcul import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_DEVICE_REPAIRED,
    SIGNAL_SHUTTER_UPDATE,
    SIGNAL_THERMOSTAT_UPDATE,
    MaxCulConnection
)

from maxcul._const import (
    ATTR_BATTERY_LOW,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    SHUTTER_CONTACT,
    SHUTTER_OPEN
)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]

    devices = []
    for device_id, device in config_entry.data.get(CONF_DEVICES).items():
        devices.append(MaxBattery(connection, device_id, device[CONF_NAME]))
        if device[CONF_TYPE] == SHUTTER_CONTACT:
            devices.append(MaxShutter(connection, device_id, device[CONF_NAME]))

    async_add_devices(devices)

    @callback
    def pairedCallback(payload):
        connection_device_path = payload.get(ATTR_CONNECTION_DEVICE_PATH)
        if connection_device_path is not device_path:
            return

        device_id = str(payload.get(ATTR_DEVICE_ID))
        device_name = payload.get(ATTR_DEVICE_SERIAL)

        devices = config_entry.data.get(CONF_DEVICES)
        if device_id in devices:
            return

        devices_to_add = []
        devices_to_add.append(MaxBattery(connection, device_id, device_name))

        device_type = payload.get(ATTR_DEVICE_TYPE)
        if device_type is SHUTTER_CONTACT:
            devices_to_add.append(MaxShutter(connection, device_id, device_name))

            new_data = {**config_entry.data}

            new_devices = devices.copy()
            new_devices[device_id] = {
                CONF_NAME: device_name,
                CONF_TYPE: SHUTTER_CONTACT
            }
            new_data[CONF_DEVICES] = new_devices

            hass.config_entries.async_update_entry(config_entry, data=new_data)

        async_add_devices(devices_to_add)

    async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, pairedCallback)
    async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, pairedCallback)


class MaxBattery(BinarySensorEntity):

    def __init__(self, connection: MaxCulConnection, device_id, name):
        self._name = name
        self._device_id = device_id
        self._connection = connection

        self._battery_low = None

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

            self._battery_low = payload.get(ATTR_BATTERY_LOW, None)

            self.async_schedule_update_ha_state()

        async_dispatcher_connect(self.hass, SIGNAL_THERMOSTAT_UPDATE, update)
        async_dispatcher_connect(self.hass, SIGNAL_SHUTTER_UPDATE, update)

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id + '-battery'

    @property
    def sender_id(self) -> int:
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_BATTERY

    @property
    def is_on(self) -> bool:
        return self._battery_low


class MaxShutter(BinarySensorEntity):

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
