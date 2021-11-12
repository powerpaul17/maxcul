from homeassistant.components.climate import (
    ClimateEntity,
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE,
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
    HEATING_THERMOSTAT
)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]
    devices = [
        MaxThermostat(connection, device_id, device[CONF_NAME])
        for device_id, device in config_entry.data.get(CONF_DEVICES).items()
        if device[CONF_TYPE] == HEATING_THERMOSTAT
    ]
    async_add_devices(devices)


class MaxThermostat(ClimateEntity):

    def __init__(self, connection: MaxCulConnection, device_id: str, name: str):
