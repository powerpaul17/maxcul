from homeassistant.config_entries import ConfigEntry

from homeassistant.core import (
    HomeAssistant,
)

from .pymaxcul.maxcul import (
    MaxConnection,
)

DOMAIN = 'maxcul'

CONF_CONNECTIONS = 'connections'

SERVICE_CONF_DEVICE_PATH = 'device_path'

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {
            CONF_CONNECTIONS: {}
        }

    device_path = config_entry.data.get(CONF_DEVICE_PATH)

    connection = MaxCulConnection(
        hass,
        device_path=device_path
    )
    connection.start()

    hass.data[DOMAIN][CONF_CONNECTIONS][device_path] = connection

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, 'climate')
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, 'binary_sensor')
    )

    return True


class MaxCulConnection:

    def __init__(self, hass, device_path):
        self._hass = hass
        self._device_path = device_path

        def callback(event, payload):
            self._callback(event, payload)

        self._connection = MaxConnection(
            device_path=device_path,
            callback=callback
        )

    def start(self):
        self._connection.start()

    def _callback(self, event, payload):
