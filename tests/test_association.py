"""Tests for MAX! thermostat and window contact associations."""

from __future__ import annotations

import pytest

from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    SERVICE_ASSOCIATE,
    SERVICE_DEASSOCIATE,
    MaxCulConnection,
)
from maxcul._const import HEATING_THERMOSTAT, SHUTTER_CONTACT
from maxcul._messages import AddLinkPartnerMessage, RemoveLinkPartnerMessage


@pytest.mark.parametrize(
    ("associate", "message_type"),
    [
        (True, AddLinkPartnerMessage),
        (False, RemoveLinkPartnerMessage),
    ],
)
def test_connection_sends_bidirectional_association_messages(
    hass,
    monkeypatch: pytest.MonkeyPatch,
    associate: bool,
    message_type: type,
) -> None:
    connection = MaxCulConnection(hass, "/dev/tty0")
    sent_messages = []
    acknowledged_messages = []
    monkeypatch.setattr(
        connection._connection,
        "_send_message",
        lambda message: sent_messages.append(message) or True,
    )
    monkeypatch.setattr(
        connection._connection,
        "_await_ack",
        acknowledged_messages.append,
    )

    connection.set_device_association(
        thermostat_id=12345,
        thermostat_type=HEATING_THERMOSTAT,
        window_contact_id=67890,
        associate=associate,
    )

    assert [type(message) for message in sent_messages] == [
        message_type,
        message_type,
    ]
    assert [message.receiver_id for message in sent_messages] == [12345, 67890]
    assert [message.assocDeviceType for message in sent_messages] == [
        SHUTTER_CONTACT,
        HEATING_THERMOSTAT,
    ]
    if associate:
        assert [message.assocDevice for message in sent_messages] == [67890, 12345]
    else:
        assert [message.assocDevice for message in sent_messages] == [
            "010932",
            "003039",
        ]
    assert [message.encode_payload() for message in sent_messages] == [
        "01093204",
        "00303901",
    ]
    assert acknowledged_messages == sent_messages


def test_connection_raises_when_association_cannot_be_queued(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = MaxCulConnection(hass, "/dev/tty0")
    monkeypatch.setattr(
        connection._connection, "_send_message", lambda _message: False
    )

    with pytest.raises(HomeAssistantError, match="operation may be partial"):
        connection.set_device_association(
            thermostat_id=12345,
            thermostat_type=HEATING_THERMOSTAT,
            window_contact_id=67890,
            associate=True,
        )


@pytest.mark.parametrize(
    ("service", "expected_associate"),
    [(SERVICE_ASSOCIATE, True), (SERVICE_DEASSOCIATE, False)],
)
@pytest.mark.parametrize(
    ("thermostat_identifier", "window_contact_identifier"),
    [
        ("67e2e", "10932"),
        ("JEQ0606104", "JHA0005822"),
    ],
)
async def test_association_service_targets_both_paired_devices(
    hass,
    max_connection_factory,
    monkeypatch: pytest.MonkeyPatch,
    service: str,
    expected_associate: bool,
    thermostat_identifier: str,
    window_contact_identifier: str,
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="association",
        data={
            CONF_DEVICE_PATH: "/dev/tty0",
            CONF_DEVICES: {
                "425518": {
                    CONF_NAME: "JEQ0606104",
                    CONF_TYPE: HEATING_THERMOSTAT,
                },
                "67890": {
                    CONF_NAME: "JHA0005822",
                    CONF_TYPE: SHUTTER_CONTACT,
                },
            },
        },
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    connection = max_connection_factory.connections["/dev/tty0"]
    calls = []
    monkeypatch.setattr(
        connection,
        "set_device_association",
        lambda thermostat_id, thermostat_type, window_contact_id, *, associate: calls.append(
            (thermostat_id, thermostat_type, window_contact_id, associate)
        ),
    )

    await hass.services.async_call(
        DOMAIN,
        service,
        {
            "thermostat_id": thermostat_identifier,
            "window_contact_id": window_contact_identifier,
        },
        blocking=True,
    )

    assert calls == [(425518, HEATING_THERMOSTAT, 67890, expected_associate)]


async def test_association_service_accepts_selected_entities(
    hass,
    max_connection_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="association-entities",
        data={
            CONF_DEVICE_PATH: "/dev/tty0",
            CONF_DEVICES: {
                "425518": {
                    CONF_NAME: "JEQ0606104",
                    CONF_TYPE: HEATING_THERMOSTAT,
                },
                "67890": {
                    CONF_NAME: "JHA0005822",
                    CONF_TYPE: SHUTTER_CONTACT,
                },
            },
        },
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    thermostat_entity = next(
        entity.entity_id
        for entity in entity_registry.entities.values()
        if entity.platform == DOMAIN and entity.unique_id == "425518"
    )
    contact_entity = next(
        entity.entity_id
        for entity in entity_registry.entities.values()
        if entity.platform == DOMAIN
        and entity.unique_id == "67890"
        and entity.entity_id.startswith("binary_sensor.")
    )

    connection = max_connection_factory.connections["/dev/tty0"]
    calls = []
    monkeypatch.setattr(
        connection,
        "set_device_association",
        lambda thermostat_id, thermostat_type, window_contact_id, *, associate: calls.append(
            (thermostat_id, thermostat_type, window_contact_id, associate)
        ),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ASSOCIATE,
        {
            "thermostat_id": thermostat_entity,
            "window_contact_id": contact_entity,
        },
        blocking=True,
    )

    assert calls == [(425518, HEATING_THERMOSTAT, 67890, True)]
