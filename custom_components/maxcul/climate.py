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

from custom_components.maxcul import (
    ATTR_CONNECTION_DEVICE_PATH,
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_DEVICE_PAIRED,
    SIGNAL_DEVICE_REPAIRED
)

from custom_components.maxcul.max_thermostat import MaxThermostat

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
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

    @callback
    def pairedCallback(payload):
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

        device = MaxThermostat(connection, device_id, device_name)
        async_add_devices([device])

        new_data = {**config_entry.data}

        new_devices = devices.copy()
        new_devices[device_id] = {
            CONF_NAME: device_name,
            CONF_TYPE: HEATING_THERMOSTAT
        }
        new_data[CONF_DEVICES] = new_devices

        hass.config_entries.async_update_entry(config_entry, data=new_data)

    async_dispatcher_connect(hass, SIGNAL_DEVICE_PAIRED, pairedCallback)
    async_dispatcher_connect(hass, SIGNAL_DEVICE_REPAIRED, pairedCallback)
