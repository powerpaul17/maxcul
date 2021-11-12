from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE
)

from homeassistant.core import (
    HomeAssistant,
)

from custom_components.maxcul import (
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    MaxCulConnection
)

from custom_components.maxcul.pymaxcul.maxcul._const import (
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


class MaxShutter(BinarySensorEntity):

    def __init__(self, connection: MaxCulConnection, device_id, name):
        self._name = name
        self._device_id = device_id
        self._connection = connection
