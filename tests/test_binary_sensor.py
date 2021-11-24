'''
Test module for binary sensors
'''

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from pytest_homeassistant_custom_component.common import (
  MockConfigEntry
)

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_BATTERY_LOW,
    ATTR_STATE,
    SHUTTER_CONTACT,
    SHUTTER_OPEN
)

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    SIGNAL_SHUTTER_UPDATE,
    async_setup_entry
)


async def test_update(hass: HomeAssistant):
    ''' Test state update of shutter contacts '''

    config = {
        CONF_DEVICE_PATH: '/dev/tty0',
        CONF_DEVICES: {
            '12345': {
                CONF_NAME: 'DEF',
                CONF_TYPE: SHUTTER_CONTACT
            }
        }
    }
    config_entry = MockConfigEntry(domain=DOMAIN, data=config, entry_id='test')

    assert await async_setup_entry(hass, config_entry)
    await hass.async_block_till_done()

    assert hass.states.get('binary_sensor.def').state == 'off'

    async_dispatcher_send(
        hass,
        SIGNAL_SHUTTER_UPDATE,
        {
            ATTR_DEVICE_ID: 12345,
            ATTR_BATTERY_LOW: False,
            ATTR_STATE: SHUTTER_OPEN
        }
    )

    await hass.async_block_till_done()

    assert hass.states.get('binary_sensor.def').state == 'on'
