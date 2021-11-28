'''
Binary sensor platform module of MaxCUL integration
'''

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    DEVICE_CLASS_BATTERY
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE,
    ENTITY_CATEGORY_DIAGNOSTIC
)

from homeassistant.core import (
    HomeAssistant,
    callback
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from maxcul._const import (
    ATTR_BATTERY_LOW,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    SHUTTER_CONTACT
)

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

from custom_components.maxcul.max_shutter import MaxShutter


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    ''' Set up the binary sensor platform for the MaxCUL integration from a config entry. '''

    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]

    devices = []
    for device_id, device in config_entry.data.get(CONF_DEVICES).items():
        devices.append(MaxBattery(connection, device_id, device[CONF_NAME]))
        if device[CONF_TYPE] == SHUTTER_CONTACT:
            devices.append(
                MaxShutter(hass, config_entry, connection, device_id, device[CONF_NAME])
            )

    async_add_devices(devices)

    @callback
    def paired_callback(payload):
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
            devices_to_add.append(
                MaxShutter(hass, config_entry, connection, device_id, device_name)
            )

        async_add_devices(devices_to_add)

    async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, paired_callback)
    async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, paired_callback)


class MaxBattery(BinarySensorEntity):
    ''' Battery sensor class of Max devices '''

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
        return self._name + '-battery'

    @property
    def unique_id(self) -> str:
        return self._device_id + '-battery'

    @property
    def sender_id(self) -> int:
        ''' Return the RF address of the device '''
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_class(self) -> str:
        return DEVICE_CLASS_BATTERY

    @property
    def entity_category(self) -> str | None:
        return ENTITY_CATEGORY_DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self._battery_low
