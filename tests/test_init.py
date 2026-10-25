import pytest

from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
  MockConfigEntry
)

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    SERVICE_ENABLE_PAIRING,
    async_setup_entry,
    normalize_device_path,
)

from maxcul import (
    EVENT_DEVICE_PAIRED,
    EVENT_DEVICE_REPAIRED,
)

from maxcul._const import (
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_DEVICE_SERIAL,
    ATTR_FIRMWARE_VERSION,
    HEATING_THERMOSTAT
)

from .conftest import MockConnectionFactory, max_connection_factory


def test_normalize_device_path():
    assert normalize_device_path("TELNET://MAXCUL.local:2323") == "maxcul.local:2323"
    assert normalize_device_path("maxcul.local:2323") == "maxcul.local:2323"
    assert normalize_device_path("/dev/ttyUSB0") == "/dev/ttyUSB0"


async def test_setup_entry(hass):
    ''' Test setting up the component from a config entry '''

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

    assert hass.data.get('entity_registry').entities.get('climate.thermostat1')


@pytest.mark.parametrize(
    "pairing_event", [EVENT_DEVICE_PAIRED, EVENT_DEVICE_REPAIRED]
)
async def test_pairing_persists_device_and_creates_entities(
    hass: HomeAssistant,
    max_connection_factory: MockConnectionFactory,
    pairing_event: str,
):
    """Persist newly announced paired or repaired devices and create their entities."""

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

    paired_payload = {
        ATTR_DEVICE_ID: 12345,
        ATTR_DEVICE_TYPE: HEATING_THERMOSTAT,
        ATTR_DEVICE_SERIAL: 'Thermostat1',
        ATTR_FIRMWARE_VERSION: 1.0
    }
    connection.call_callback(pairing_event, paired_payload)
    connection.call_callback(pairing_event, paired_payload)

    await hass.async_block_till_done()
    await hass.async_block_till_done()

    assert hass.data.get('entity_registry').entities.get('climate.thermostat1')
    assert len(hass.states.async_entity_ids('climate')) == 1
    assert len(hass.states.async_entity_ids('binary_sensor')) == 1

    device_registry = dr.async_get(hass)
    device = next(
        device
        for device in dr.async_entries_for_config_entry(
            device_registry, config_entry.entry_id
        )
        if (DOMAIN, "12345") in device.identifiers
    )
    assert device.model == "Thermostat"

    device = config_entry.data.get(CONF_DEVICES).get('12345')
    assert device == {
        CONF_NAME: 'Thermostat1',
        CONF_TYPE: HEATING_THERMOSTAT
    }


async def test_enable_pairing_uses_only_loaded_cul_when_path_is_omitted(
    hass: HomeAssistant,
    max_connection_factory: MockConnectionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_PATH: "/dev/tty0", CONF_DEVICES: {}},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    calls = []
    monkeypatch.setattr(
        max_connection_factory.connections["/dev/tty0"],
        "enable_pairing",
        calls.append,
    )
    await hass.services.async_call(DOMAIN, SERVICE_ENABLE_PAIRING, {}, blocking=True)

    assert calls == [30]


async def test_enable_pairing_requires_path_when_multiple_culs_are_loaded(
    hass: HomeAssistant,
    max_connection_factory: MockConnectionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serial_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_PATH: "/dev/tty0", CONF_DEVICES: {}},
    )
    network_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DEVICE_PATH: "telnet://maxcul.local:2323", CONF_DEVICES: {}},
    )
    serial_entry.add_to_hass(hass)
    network_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(serial_entry.entry_id)
    assert await hass.config_entries.async_setup(network_entry.entry_id)
    await hass.async_block_till_done()

    calls = []
    monkeypatch.setattr(
        max_connection_factory.connections["telnet://maxcul.local:2323"],
        "enable_pairing",
        calls.append,
    )
    with pytest.raises(HomeAssistantError, match="specify device_path"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ENABLE_PAIRING, {}, blocking=True
        )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ENABLE_PAIRING,
        {"device_path": "MAXCUL.local:2323", "duration": 45},
        blocking=True,
    )

    assert calls == [45]
