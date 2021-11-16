from homeassistant.config_entries import ConfigEntry
import voluptuous

from homeassistant.core import (
    HomeAssistant,
    ServiceCall
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send

from maxcul import (
    MaxConnection,
    EVENT_DEVICE_PAIRED,
    EVENT_DEVICE_REPAIRED,
    EVENT_SHUTTER_UPDATE,
    EVENT_THERMOSTAT_UPDATE
)

DOMAIN = 'maxcul'

CONF_CONNECTIONS = 'connections'
CONF_DEVICE_PATH = 'device_path'

SERVICE_CONF_DEVICE_PATH = 'device_path'
SERVICE_CONF_DURATION = 'duration'

ENABLE_PAIRING_SERVICE_SCHEMA = voluptuous.Schema({
    voluptuous.Required(SERVICE_CONF_DEVICE_PATH): cv.string,
    voluptuous.Optional(SERVICE_CONF_DURATION, default=30): cv.positive_int
})

SIGNAL_DEVICE_PAIRED = DOMAIN + '.device_paired'
SIGNAL_DEVICE_REPAIRED = DOMAIN + '.device_repaired'
SIGNAL_THERMOSTAT_UPDATE = DOMAIN + '.thermostat_update'
SIGNAL_SHUTTER_UPDATE = DOMAIN + '.shutter_update'

ATTR_CONNECTION_DEVICE_PATH = 'connection_device_path'

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

    def _service_enable_pairing(service: ServiceCall):
        service_device_path = service.data[SERVICE_CONF_DEVICE_PATH]
        duration = service.data[SERVICE_CONF_DURATION]

        if service_device_path != device_path:
            return

        connection.enable_pairing(duration)

    hass.services.async_register(
        DOMAIN,
        'enable_pairing',
        _service_enable_pairing,
        schema=ENABLE_PAIRING_SERVICE_SCHEMA
    )

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
        if event == EVENT_DEVICE_PAIRED:
            payload[ATTR_CONNECTION_DEVICE_PATH] = self._device_path
            dispatcher_send(self._hass, SIGNAL_DEVICE_PAIRED, payload)

        elif event == EVENT_DEVICE_REPAIRED:
            payload[ATTR_CONNECTION_DEVICE_PATH] = self._device_path
            dispatcher_send(self._hass, SIGNAL_DEVICE_REPAIRED, payload)

        elif event == EVENT_THERMOSTAT_UPDATE:
            dispatcher_send(self._hass, SIGNAL_THERMOSTAT_UPDATE, payload)

        elif event == EVENT_SHUTTER_UPDATE:
            dispatcher_send(self._hass, SIGNAL_SHUTTER_UPDATE, payload)

    def enable_pairing(self, duration):
        self._connection.enable_pairing(duration)

    def add_paired_device(self, device_id):
        self._connection.add_paired_device(device_id)

    def set_temperature(self, device_id: str, target_temperature: float, mode):
        self._connection.set_temperature(
            device_id,
            target_temperature,
            mode
        )
