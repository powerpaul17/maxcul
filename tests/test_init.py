from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
  MockConfigEntry
)

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    async_setup_entry
)

from maxcul import (
    EVENT_DEVICE_PAIRED
)

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    ATTR_FIRMWARE_VERSION,
    HEATING_THERMOSTAT
)

from .conftest import MockConnectionFactory, max_connection_factory


async def test_setup_entry(hass):
    ''' Test setting up the component from a config entry '''

    config = {
        CONF_DEVICE_PATH: '/dev/tty0',
        CONF_DEVICES: {
            '12345': {
                CONF_NAME: 'DEF',
                CONF_TYPE: HEATING_THERMOSTAT
            }
        }
    }
    config_entry = MockConfigEntry(domain=DOMAIN, data=config, entry_id='test')
    assert await async_setup_entry(hass, config_entry)

    await hass.async_block_till_done()

    assert hass.data.get('entity_registry').entities.get('climate.def')


async def test_pairing(hass: HomeAssistant, max_connection_factory: MockConnectionFactory):
    ''' Test pairing of device '''

    config = {
        CONF_DEVICE_PATH: '/dev/tty0',
        CONF_DEVICES: {}
    }
    config_entry = MockConfigEntry(domain=DOMAIN, data=config, entry_id='test')

    assert await async_setup_entry(hass, config_entry)
    await hass.async_block_till_done()

    assert not hass.data.get('entity_registry').entities

    connection = max_connection_factory.connections[config[CONF_DEVICE_PATH]]
    assert connection

    connection.call_callback(
        EVENT_DEVICE_PAIRED,
        {
            ATTR_DEVICE_ID: 12345,
            ATTR_DEVICE_TYPE: HEATING_THERMOSTAT,
            ATTR_DEVICE_SERIAL: 'DEF',
            ATTR_FIRMWARE_VERSION: 1.0
        }
    )

    await hass.async_block_till_done()
    await hass.async_block_till_done()

    assert hass.data.get('entity_registry').entities.get('climate.def')

    device = config_entry.data.get(CONF_DEVICES).get('12345')
    assert device == {
        CONF_NAME: 'DEF',
        CONF_TYPE: HEATING_THERMOSTAT
    }
