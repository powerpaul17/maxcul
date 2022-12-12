'''
MaxCUL custom component for Home Assistant
'''

import voluptuous

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_DEVICES
)

from homeassistant.core import (
    HomeAssistant,
    ServiceCall
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers import device_registry as dr

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

CONF_SENDER_ID = 'sender_id'

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
    ''' Set up MaxCUL custom component from a config entry '''

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {
            CONF_CONNECTIONS: {}
        }

    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    sender_id = config_entry.options.get(CONF_SENDER_ID)

    connection = MaxCulConnection(
        hass,
        device_path=device_path,
        sender_id=sender_id
    )
    connection.start()

    hass.data[DOMAIN][CONF_CONNECTIONS][device_path] = connection

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, config_entry.entry_id):
        for (_, device_id) in device_entry.identifiers:
            if device_id not in config_entry.data.get(CONF_DEVICES).keys():
                device_registry.async_remove_device(device_entry.id)

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

    def __init__(self, hass: HomeAssistant, device_path: str, sender_id=None):
        self._hass = hass
        self._device_path = device_path

        if not sender_id:
            sender_id = 0x123456

        def callback(event, payload):
            self._callback(event, payload)

        self._connection = MaxConnection(
            device_path=device_path,
            callback=callback,
            sender_id=sender_id
        )

    def start(self):
        ''' Start the connection thread '''
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
        ''' Enable pairing of devices '''
        self._connection.enable_pairing(duration)

    def add_paired_device(self, device_id):
        ''' Add a device id to the paired devices '''
        self._connection.add_paired_device(device_id)

    def set_temperature(self, device_id: int, target_temperature: float, mode):
        ''' Set the target temperature of a thermostat device '''

        self._connection.set_temperature(
            device_id,
            target_temperature,
            mode
        )
