import time

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_DEVICES
)

import serial.tools.list_ports
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components import usb

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN
)

from serial import Serial, SerialException
from custom_components.maxcul.pymaxcul.maxcul._telnet import TelnetSerial

CONF_MANUAL_PATH = 'Enter manually'

CONF_DEVICE_TYPE = 'device_type'

class MaxculFlowHandler(ConfigFlow, domain=DOMAIN):

    def __init__(self) -> None:
        self._com_ports = []

    async def async_step_user(self, user_input=None) -> FlowResult:
        self._com_ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)

        if not len(self._com_ports):
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

async def test_connection(device_path: str) -> bool:
    com_port = None
    try:
        if device_path.startswith('telnet://'):
            com_port = TelnetSerial(device_path)
        else:
            com_port = Serial(device_path)
    except:
        return False

    return get_cul_version(com_port)

def get_cul_version(com_port: Serial) -> bool:
    cul_version = None

    # was required for my nanoCUL
    time.sleep(2)

    # get CUL FW version
    for _ in range(10):
        com_port.write(b'V')
        time.sleep(1)
        cul_version = com_port.readline() or None
        if cul_version is not None:
            break

    if cul_version is None:
        com_port.close()
        com_port = None
        return False

    return True
