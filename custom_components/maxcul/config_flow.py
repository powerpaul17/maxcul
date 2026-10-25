"""Config flow for the MaxCUL integration."""

from __future__ import annotations

import ipaddress
import logging
import time
from typing import Any

import serial.tools.list_ports
import voluptuous as vol
from homeassistant.components import usb
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_DEVICES, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from serial import Serial, SerialException

from maxcul._telnet import TelnetSerial

from . import (
    CONF_DEVICE_PATH,
    CONF_SENDER_ID,
    DOMAIN,
    normalize_device_path,
)

LOGGER = logging.getLogger(__name__)

CONF_MANUAL_PATH = "Enter manually"
CONF_DEVICE_TYPE = "device_type"


class MaxculFlowHandler(ConfigFlow, domain=DOMAIN):
    """Configure a MaxCUL serial or network connection."""

    def __init__(self) -> None:
        self._com_ports: list[Any] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose a serial or network connection."""
        try:
            self._com_ports = await self.hass.async_add_executor_job(
                serial.tools.list_ports.comports
            )
        except (OSError, SerialException) as err:
            LOGGER.warning("Unable to list serial ports: %s", err)
            self._com_ports = []

        if user_input is not None:
            if user_input[CONF_DEVICE_TYPE] == "serial port":
                return await self.async_step_device_picker()
            return await self.async_step_pick_host()

        schema = vol.Schema(
            {vol.Required(CONF_DEVICE_TYPE): vol.In(["serial port", "network"])}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_device_picker(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a serial device."""
        port_labels = []
        for port in self._com_ports:
            label = f"{port.description or port.device} ({port.device})"
            label += f", s/n: {port.serial_number or 'n/a'}"
            if port.manufacturer:
                label += f" - {port.manufacturer}"
            port_labels.append(label)

        if not port_labels:
            return await self.async_step_manual_device_path()

        port_labels.append(CONF_MANUAL_PATH)
        errors: dict[str, str] = {}

        if user_input is not None:
            user_selection = user_input[CONF_DEVICE_PATH]
            if user_selection == CONF_MANUAL_PATH:
                return await self.async_step_manual_device_path()

            port = self._com_ports[port_labels.index(user_selection)]
            device_path = await self.hass.async_add_executor_job(
                usb.get_serial_by_id, port.device
            )
            device_path = device_path or port.device

            if await test_connection(self.hass, device_path):
                title = port.description or port.device
                title += f" (s/n: {port.serial_number or 'n/a'})"
                if port.manufacturer:
                    title += f" - {port.manufacturer}"
                return await self._async_create_entry(device_path, title)

            errors["base"] = "cannot_connect_to_device"

        schema = vol.Schema({vol.Required(CONF_DEVICE_PATH): vol.In(port_labels)})
        return self.async_show_form(
            step_id="device_picker", data_schema=schema, errors=errors
        )

    async def async_step_manual_device_path(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter a serial device path or telnet URL manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_path = user_input[CONF_DEVICE_PATH].strip()
            if await test_connection(self.hass, device_path):
                return await self._async_create_entry(device_path, device_path)
            errors["base"] = "cannot_connect_to_device"

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_PATH): vol.All(
                    cv.string, vol.Length(min=1)
                )
            }
        )
        return self.async_show_form(
            step_id="manual_device_path", data_schema=schema, errors=errors
        )

    async def async_step_pick_host(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Enter a host and port for a network-connected CUL device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            formatted_host = host
            try:
                address = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                pass
            else:
                if address.version == 6:
                    formatted_host = f"[{address.compressed}]"

            device_path = f"telnet://{formatted_host}:{port}"

            if await test_connection(self.hass, device_path):
                return await self._async_create_entry(device_path, f"{host}:{port}")
            errors["base"] = "cannot_connect_to_device"

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): vol.All(cv.string, vol.Length(min=1)),
                vol.Optional(CONF_PORT, default=2323): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        )
        return self.async_show_form(
            step_id="pick_host", data_schema=schema, errors=errors
        )

    async def _async_create_entry(self, device_path: str, title: str) -> FlowResult:
        """Create an entry after ensuring its connection path is unique."""
        unique_id = normalize_device_path(device_path)
        if any(
            existing.data.get(CONF_DEVICE_PATH)
            and normalize_device_path(existing.data[CONF_DEVICE_PATH]) == unique_id
            for existing in self.hass.config_entries.async_entries(DOMAIN)
        ):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=title,
            data={CONF_DEVICE_PATH: device_path, CONF_DEVICES: {}},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the sender-ID options flow."""
        return MaxculOptionsFlowHandler(config_entry)


async def test_connection(hass: HomeAssistant, device_path: str) -> bool:
    """Check that a serial or telnet device responds as a CUL."""
    return await hass.async_add_executor_job(_test_connection, device_path)


def _test_connection(device_path: str) -> bool:
    """Open, probe, and close a CUL device outside the event loop."""
    connection: Serial | TelnetSerial | None = None
    try:
        if device_path.casefold().startswith("telnet://"):
            telnet_path = f"telnet://{device_path[len('telnet://'):]}"
            connection = TelnetSerial(telnet_path, 0.5)
        else:
            connection = Serial(device_path, timeout=0.5)

        # Some CUL devices need time to initialize before they answer commands.
        return _get_cul_version(connection)
    except (OSError, SerialException, ValueError) as err:
        LOGGER.debug("Unable to connect to MaxCUL device %s: %s", device_path, err)
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except (OSError, SerialException) as err:
                LOGGER.debug("Unable to close MaxCUL device %s: %s", device_path, err)


def _get_cul_version(connection: Serial | TelnetSerial) -> bool:
    """Wait for the CUL firmware response to a version request."""
    time.sleep(2)
    for _ in range(10):
        connection.write(b"V\n")
        time.sleep(1)
        if connection.readline():
            return True
    return False


class MaxculOptionsFlowHandler(OptionsFlow):
    """Allow configuring the MaxCUL sender ID."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show or save the sender ID."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        sender_id = self._config_entry.options.get(CONF_SENDER_ID)
        if sender_id is None:
            sender_id = 0x123456

        schema = vol.Schema(
            {
                vol.Optional(CONF_SENDER_ID, default=sender_id): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=0xFFFFFF)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
