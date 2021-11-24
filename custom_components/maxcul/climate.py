'''
Climate platform module of MaxCUL integration
'''

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE
)

from homeassistant.core import (
    HomeAssistant,
    callback
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    HEATING_THERMOSTAT
)

from custom_components.maxcul import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_DEVICE_REPAIRED
)

from custom_components.maxcul.max_thermostat import MaxThermostat


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    ''' Set up the climate platform for the MaxCUL integration from a config entry. '''

    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]

    devices = [
        MaxThermostat(
            hass,
            config_entry,
            connection,
            device_id,
            device[CONF_NAME]
        )
        for device_id, device in config_entry.data.get(CONF_DEVICES).items()
        if device[CONF_TYPE] == HEATING_THERMOSTAT
    ]
    async_add_devices(devices)

    @callback
    def paired_callback(payload):
        connection_device_path = payload.get(ATTR_CONNECTION_DEVICE_PATH)
        if connection_device_path is not device_path:
            return

        device_type = payload.get(ATTR_DEVICE_TYPE)
        if device_type is not HEATING_THERMOSTAT:
            return

        device_id = str(payload.get(ATTR_DEVICE_ID))
        device_name = payload.get(ATTR_DEVICE_SERIAL)

        devices = config_entry.data.get(CONF_DEVICES)
        if device_id in devices:
            return

        device = MaxThermostat(hass, config_entry, connection, device_id, device_name)
        async_add_devices([device])

    async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, paired_callback)
    async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, paired_callback)
