"""Tests for MAX! thermostat week profiles."""

from __future__ import annotations

import pytest

from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.exceptions import HomeAssistantError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maxcul import (
    CONF_DEVICE_PATH,
    DOMAIN,
    SERVICE_SET_WEEK_PROFILE,
    MaxCulConnection,
)
from custom_components.maxcul.week_profile import (
    WeekProfileChunk,
    compile_week_profile,
)
from maxcul._const import HEATING_THERMOSTAT
from maxcul._messages import AckMessage


def _complete_profile(saturday: str = "Sat 20") -> str:
    return "\n".join(
        (
            saturday,
            "Sun 20",
            "Mon 21,06:00,17,22:00,16",
            "Tue 20",
            "Wed 20",
            "Thu 20",
            "Fri 20",
        )
    )


def test_compile_week_profile_builds_max_day_ordered_chunks() -> None:
    chunks = compile_week_profile(_complete_profile())

    assert [chunk.day for chunk in chunks] == list(range(7))
    assert all(chunk.part == 0 for chunk in chunks)
    assert chunks[0].payload == "005120" + "4520" * 6
    assert chunks[2].payload == (
        "02"
        "5448"
        "4508"
        "4120"
        "4520" * 4
    )


def test_compile_week_profile_sends_second_part_for_long_day() -> None:
    profile = _complete_profile(
        "Sat 20,01:00,19,02:00,18,03:00,17,04:00,16,05:00,15,06:00,14,07:00,13"
    )

    chunks = compile_week_profile(profile)

    assert [(chunk.day, chunk.part) for chunk in chunks[:2]] == [(0, 0), (0, 1)]
    assert chunks[0].payload.startswith("00")
    assert chunks[1].payload.startswith("08")
    assert len(chunks[1].payload) == 26


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ("Mon 20", "unvollständig"),
        (_complete_profile("Sat 20\nSat 19"), "mehrfach"),
        (_complete_profile("Sat 31"), "Temperatur"),
        (_complete_profile("Sat 20,06:03,19"), "Uhrzeit"),
        (_complete_profile("Sat 20,06:00,19,05:00,18"), "aufsteigend"),
    ],
)
def test_compile_week_profile_rejects_invalid_profiles(
    profile: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        compile_week_profile(profile)


def test_connection_sends_profile_as_config_week_profile_messages(
    hass, monkeypatch: pytest.MonkeyPatch
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

    connection.set_week_profile(
        12345, compile_week_profile(_complete_profile()), "profile-request"
    )

    assert len(sent_messages) == 7
    assert acknowledged_messages == sent_messages
    assert sent_messages[0].encode_message() == (
        "Zs1901001012345600303900005120452045204520452045204520"
    )


def test_connection_raises_when_profile_cannot_be_queued(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = MaxCulConnection(hass, "/dev/tty0")
    monkeypatch.setattr(
        connection._connection, "_send_message", lambda _message: False
    )

    with pytest.raises(HomeAssistantError, match="Could not queue week profile"):
        connection.set_week_profile(
            12345, [WeekProfileChunk(0, 0, "005120")], "profile-request"
        )


def test_connection_reports_acknowledged_week_profile(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = MaxCulConnection(hass, "/dev/tty0")
    monkeypatch.setattr(connection._connection, "_send_message", lambda _message: True)
    monkeypatch.setattr(connection._connection, "_await_ack", lambda _message: None)
    events = []
    monkeypatch.setattr(
        connection,
        "_callback",
        lambda event, payload: events.append((event, payload)),
    )

    connection.set_week_profile(
        12345,
        [WeekProfileChunk(0, 0, "005120")],
        "profile-request",
    )
    counter = next(iter(connection._week_profile_counters))
    connection._handle_week_profile_ack(
        AckMessage(counter=counter, sender_id=12345, state="ok")
    )

    assert events[-1][1]["status"] == "acknowledged"
    assert events[-1][1]["request_id"] == "profile-request"


@pytest.mark.parametrize(
    "thermostat_identifier",
    ["12345", "3039", "Thermostat", "climate.thermostat"],
)
async def test_set_week_profile_service_targets_paired_thermostat(
    hass,
    max_connection_factory,
    monkeypatch: pytest.MonkeyPatch,
    thermostat_identifier: str,
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="week-profile",
        data={
            CONF_DEVICE_PATH: "/dev/tty0",
            CONF_DEVICES: {
                "12345": {
                    CONF_NAME: "Thermostat",
                    CONF_TYPE: HEATING_THERMOSTAT,
                }
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
        "set_week_profile",
        lambda device_id, chunks, request_id: calls.append(
            (device_id, chunks, request_id)
        ),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_WEEK_PROFILE,
        {
            "device_id": thermostat_identifier,
            "week_profile": _complete_profile(),
        },
        blocking=True,
    )

    assert len(calls) == 1
    assert calls[0][0] == 12345
    assert len(calls[0][1]) == 7
    assert calls[0][2]
    assert config_entry.data["week_profiles"]["12345"] == {
        "profile": _complete_profile(),
        "request_id": calls[0][2],
        "status": "pending",
    }
