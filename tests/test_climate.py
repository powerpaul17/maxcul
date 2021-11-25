'''
Test module for climate entities
'''

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from homeassistant.components.climate import (
    HVAC_MODE_HEAT
)

from pytest_homeassistant_custom_component.common import (
  MockConfigEntry
)

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_BATTERY_LOW,
    ATTR_MEASURED_TEMPERATURE,
    ATTR_DESIRED_TEMPERATURE,
    ATTR_VALVE_POSITION,
    ATTR_MODE,
    HEATING_THERMOSTAT,
    MODE_MANUAL
)

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_THERMOSTAT_UPDATE,
    async_setup_entry
)


async def test_update(hass: HomeAssistant):
    ''' Test updating of thermostat state '''
    config = {
        CONF_DEVICE_PATH: '/dev/tty0',
        CONF_DEVICES: {
            '12345': {
                CONF_NAME: 'Thermostat1',
                CONF_TYPE: HEATING_THERMOSTAT
            }
        }
    }
    config_entry = MockConfigEntry(domain=DOMAIN, data=config, entry_id='test')

    assert await async_setup_entry(hass, config_entry)
    await hass.async_block_till_done()

    assert hass.states.get('climate.thermostat1').state == 'unknown'

    async_dispatcher_send(
        hass,
        SIGNAL_THERMOSTAT_UPDATE,
        {
            ATTR_DEVICE_ID: 12345,
            ATTR_MEASURED_TEMPERATURE: 23.0,
            ATTR_DESIRED_TEMPERATURE: 21.5,
            ATTR_VALVE_POSITION: 0,
            ATTR_MODE: MODE_MANUAL,
            ATTR_BATTERY_LOW: False
        }
    )

    await hass.async_block_till_done()

    state = hass.states.get('climate.thermostat1')
    assert state.state == HVAC_MODE_HEAT
    assert state.attributes.get('temperature') == 21.5
    assert state.attributes.get('current_temperature') == 23.0

