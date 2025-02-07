'''
Config flow for MaxCUL custom component
'''

import asyncio

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_DEVICES
)

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow
)

from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components import usb

from serial import Serial
from maxcul._telnet import TelnetSerial
import serial.tools.list_ports
import voluptuous as vol

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    CONF_SENDER_ID,
    DOMAIN
)

CONF_MANUAL_PATH = 'Enter manually'

CONF_DEVICE_TYPE = 'device_type'

class MaxculFlowHandler(ConfigFlow, domain=DOMAIN):
    ''' Config flow handler for MaxCUL custom component '''

    def __init__(self) -> None:
        self._com_ports = []

    async def async_step_user(self, user_input=None) -> FlowResult:
        self._com_ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)

        if not self._com_ports:
            return await self.async_step_pick_host()

        if user_input is not None:
            if user_input[CONF_DEVICE_TYPE] == 'serial port':
                return await self.async_step_device_picker()

            elif user_input[CONF_DEVICE_TYPE] == 'network':
                return await self.async_step_pick_host()

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_TYPE): vol.In([ 'serial port', 'network' ])
        })
        return self.async_show_form(step_id='user', data_schema=schema)

    async def async_step_device_picker(self, user_input=None) -> FlowResult:
        ''' Step for picking a serial device '''

        list_of_ports = [
            f"{p}, s/n: {p.serial_number or 'n/a'}"
            + (f" - {p.manufacturer}" if p.manufacturer else '')
            for p in self._com_ports
        ]

        if not list_of_ports:
            return await self.async_step_pick_host()

        list_of_ports.append(CONF_MANUAL_PATH)

        errors = {}

        if user_input is not None:
            user_selection = user_input[CONF_DEVICE_PATH]
            if user_selection == CONF_MANUAL_PATH:
                return await self.async_step_manual_device_path()

            port = self._com_ports[list_of_ports.index(user_selection)]
            device_path = await self.hass.async_add_executor_job(
                usb.get_serial_by_id, port.device
            )

            if await test_connection(device_path):
                title = f"{port.description}, s/n: {port.serial_number or 'n/a'}"
                title += f" - {port.manufacturer}" if port.manufacturer else ''

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_DEVICE_PATH: device_path,
                        CONF_DEVICES: {}
                    }
                )

            errors['base'] = 'cannot_connect_to_device'

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_PATH): vol.In(list_of_ports)
        })
        return self.async_show_form(step_id='device_picker', data_schema=schema, errors=errors)

    async def async_step_manual_device_path(self, user_input=None) -> FlowResult:
        ''' Step for entering a device path manually '''

        errors = {}

        if user_input is not None:
            device_path = user_input[CONF_DEVICE_PATH]

            if await test_connection(device_path):
                return self.async_create_entry(
                    title=device_path,
                    data={
                        CONF_DEVICE_PATH: device_path,
                        CONF_DEVICES: {}
                    }
                )

            errors['base'] = 'cannot_connect_to_device'

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_PATH): str
        })
        return self.async_show_form(step_id='manual_device_path', data_schema=schema, errors=errors)

    async def async_step_pick_host(self, user_input=None) -> FlowResult:
        ''' Step for entering a host/port combination for network connections of CUL devices '''

        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            device_path='telnet://' + host + ':' + str(port)

            if await test_connection(device_path):
                return self.async_create_entry(
                    title=host + ':' + str(port),
                    data={
                        CONF_DEVICE_PATH: device_path,
                        CONF_DEVICES: {}
                    }
                )

            errors['base'] = 'cannot_connect_to_device'

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_PORT, default=2323): int
        })
        return self.async_show_form(step_id='pick_host', data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return MaxculOptionsFlowHandler(config_entry)


async def test_connection(device_path: str) -> bool:
    ''' Check if device is reachable and a CUL device '''

    com_port = None
    try:
        if device_path.startswith('telnet://'):
            com_port = TelnetSerial(device_path, 0.5)
        else:
            com_port = Serial(device_path)
    except:
        return False

    return await get_cul_version(com_port)

async def get_cul_version(com_port: Serial or TelnetSerial) -> bool:
    ''' Determine CUL version of serial/telnet device '''

    cul_version = None

    # was required for my nanoCUL
    await asyncio.sleep(2)

    # get CUL FW version
    for _ in range(10):
        com_port.write(b'V\n')
        await asyncio.sleep(1)
        cul_version = com_port.readline() or None
        if cul_version is not None:
            break

    if cul_version is None:
        com_port.close()
        com_port = None
        return False

    return True


class MaxculOptionsFlowHandler(OptionsFlow):
    ''' Options flow handler for MaxCUL custom component '''

    def __init__(self, config_entry: ConfigEntry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        ''' Start an options flow '''

        errors = {}

        if user_input is not None:
            return self.async_create_entry(title='', data=user_input)

        sender_id = self._config_entry.options.get(CONF_SENDER_ID) or 0x123456
        schema = vol.Schema({
            vol.Optional(CONF_SENDER_ID, default=sender_id): int
        })
        return self.async_show_form(step_id='init', data_schema=schema, errors=errors)
