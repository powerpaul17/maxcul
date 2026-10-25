"""MaxCUL custom component for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICES, CONF_NAME, CONF_TYPE
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send
from homeassistant.helpers.typing import ConfigType

from maxcul import (
    EVENT_DEVICE_PAIRED,
    EVENT_DEVICE_REPAIRED,
    EVENT_SHUTTER_UPDATE,
    EVENT_THERMOSTAT_UPDATE,
    MaxConnection,
)
from maxcul._const import (
    ATTR_DEVICE_ID,
    DEVICE_TYPES_BY_NAME,
    HEATING_THERMOSTAT,
    HEATING_THERMOSTAT_PLUS,
    SHUTTER_CONTACT,
    WALL_MOUNTED_THERMOSTAT,
)
from maxcul._messages import (
    AckMessage,
    AddLinkPartnerMessage,
    ConfigWeekProfileMessage,
    RemoveLinkPartnerMessage,
)

from .week_profile import WeekProfileChunk, compile_week_profile

LOGGER = logging.getLogger(__name__)

DOMAIN = "maxcul"

PLATFORMS = ["climate", "binary_sensor"]

CONF_DEVICE_PATH = "device_path"
CONF_SENDER_ID = "sender_id"

SERVICE_ENABLE_PAIRING = "enable_pairing"
SERVICE_CONF_DEVICE_PATH = "device_path"
SERVICE_CONF_DURATION = "duration"
SERVICE_SET_WEEK_PROFILE = "set_week_profile"
SERVICE_CONF_DEVICE_ID = "device_id"
SERVICE_CONF_WEEK_PROFILE = "week_profile"
CONF_WEEK_PROFILES = "week_profiles"
SERVICE_ASSOCIATE = "associate"
SERVICE_DEASSOCIATE = "deassociate"
SERVICE_CONF_THERMOSTAT_ID = "thermostat_id"
SERVICE_CONF_WINDOW_CONTACT_ID = "window_contact_id"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ENABLE_PAIRING_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(SERVICE_CONF_DEVICE_PATH): cv.string,
        vol.Optional(SERVICE_CONF_DURATION, default=30): vol.All(
            cv.positive_int, vol.Range(max=300)
        ),
    }
)
SET_WEEK_PROFILE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_CONF_DEVICE_ID): cv.string,
        vol.Required(SERVICE_CONF_WEEK_PROFILE): cv.string,
        vol.Optional(SERVICE_CONF_DEVICE_PATH): cv.string,
    }
)
DEVICE_ASSOCIATION_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_CONF_THERMOSTAT_ID): cv.string,
        vol.Required(SERVICE_CONF_WINDOW_CONTACT_ID): cv.string,
        vol.Optional(SERVICE_CONF_DEVICE_PATH): cv.string,
    }
)

SIGNAL_DEVICE_PAIRED = f"{DOMAIN}.device_paired"
SIGNAL_DEVICE_REPAIRED = f"{DOMAIN}.device_repaired"
SIGNAL_THERMOSTAT_UPDATE = f"{DOMAIN}.thermostat_update"
SIGNAL_SHUTTER_UPDATE = f"{DOMAIN}.shutter_update"
SIGNAL_WEEK_PROFILE_UPDATE = f"{DOMAIN}.week_profile_update"
EVENT_WEEK_PROFILE_UPDATE = f"{DOMAIN}.week_profile_update"

ATTR_CONNECTION_DEVICE_PATH = "connection_device_path"

type MaxCulConfigEntry = ConfigEntry[MaxCulConnection]


@dataclass
class _WeekProfileRequest:
    """Track acknowledgement state for the chunks of one profile update."""

    device_id: int
    pending_counters: set[int] = field(default_factory=set)
    ready: bool = False
    failed: bool = False


def normalize_device_path(path: str) -> str:
    """Canonicalize serial paths and network addresses for matching."""
    normalized_path = path.strip()
    if normalized_path.casefold().startswith("telnet://"):
        normalized_path = normalized_path[len("telnet://") :]

    if not normalized_path.startswith("/") and ":" in normalized_path:
        host, separator, port = normalized_path.rpartition(":")
        if separator and port.isdecimal():
            return f"{host.casefold()}:{port}"

    return normalized_path


def _find_paired_device_candidates(
    known_devices: dict[str, Any], identifier: str
) -> list[tuple[str, dict[str, Any]]]:
    """Find paired devices by hexadecimal address or saved friendly name."""
    normalized_identifier = identifier.strip().casefold()
    matching_devices: list[tuple[str, dict[str, Any]]] = []

    try:
        numeric_id = int(identifier, 16)
    except ValueError:
        numeric_id = None

    for device_id, device in known_devices.items():
        if not isinstance(device, dict):
            continue
        address_matches = device_id == identifier or (
            numeric_id is not None and device_id == str(numeric_id)
        )
        name = device.get(CONF_NAME)
        name_matches = (
            isinstance(name, str) and name.strip().casefold() == normalized_identifier
        )
        if address_matches or name_matches:
            matching_devices.append((device_id, device))

    return matching_devices


def _resolve_association_entity(
    hass: HomeAssistant, entity_id: str, expected_domain: str
) -> str | None:
    """Resolve a MaxCUL entity selector value to its paired-device ID."""
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None:
        return None
    entity_domain = entity_entry.entity_id.partition(".")[0]
    if entity_entry.platform != DOMAIN or entity_domain != expected_domain:
        raise ServiceValidationError(
            f"Selected entity {entity_id} is not a MaxCUL {expected_domain} entity"
        )
    return entity_entry.unique_id


def register_paired_device(
    hass: HomeAssistant,
    config_entry: MaxCulConfigEntry,
    device_id: str,
    name: str,
    device_type: str,
) -> None:
    """Persist a newly paired device without replacing other entry data."""
    known_devices = config_entry.data.get(CONF_DEVICES) or {}
    device = {CONF_NAME: name, CONF_TYPE: device_type}
    if known_devices.get(device_id) == device:
        return

    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_DEVICES: {**known_devices, device_id: device},
        },
    )


def _store_week_profile_state(
    hass: HomeAssistant,
    config_entry: MaxCulConfigEntry,
    device_id: int,
    profile: str,
    request_id: str,
    status: str,
) -> None:
    """Persist the latest profile and notify the thermostat entity."""
    device_key = str(device_id)
    profiles = config_entry.data.get(CONF_WEEK_PROFILES) or {}
    profile_state = {
        "profile": profile,
        "request_id": request_id,
        "status": status,
    }
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_WEEK_PROFILES: {**profiles, device_key: profile_state},
        },
    )
    dispatcher_send(
        hass,
        SIGNAL_WEEK_PROFILE_UPDATE,
        {
            "device_id": device_key,
            ATTR_CONNECTION_DEVICE_PATH: config_entry.data[CONF_DEVICE_PATH],
            **profile_state,
        },
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the MaxCUL integration and register its service actions.

    Service actions are registered here (not in async_setup_entry), so they
    exist even when no config entry is loaded and automations can be validated.
    """

    @callback
    def _service_enable_pairing(service: ServiceCall) -> None:
        service_device_path = service.data.get(SERVICE_CONF_DEVICE_PATH)
        normalized_service_path = (
            normalize_device_path(service_device_path)
            if service_device_path
            else None
        )
        duration = service.data[SERVICE_CONF_DURATION]

        matching_entries = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if normalized_service_path is None
            or (
                entry.data.get(CONF_DEVICE_PATH)
                and normalize_device_path(entry.data[CONF_DEVICE_PATH])
                == normalized_service_path
            )
        ]

        if len(matching_entries) == 1:
            matching_entries[0].runtime_data.enable_pairing(duration)
            return

        if len(matching_entries) > 1:
            raise ServiceValidationError(
                "Multiple MaxCUL connections are loaded; specify device_path"
            )

        raise ServiceValidationError(
            "No loaded MaxCUL connection found"
            if normalized_service_path is None
            else f"No loaded MaxCUL connection found for {service_device_path}"
        )

    @callback
    def _service_set_week_profile(service: ServiceCall) -> None:
        device_identifier = service.data[SERVICE_CONF_DEVICE_ID]
        selected_entity_id = _resolve_association_entity(
            hass, device_identifier, "climate"
        )
        if selected_entity_id is not None:
            device_identifier = selected_entity_id
        service_device_path = service.data.get(SERVICE_CONF_DEVICE_PATH)
        normalized_service_path = (
            normalize_device_path(service_device_path)
            if service_device_path
            else None
        )
        try:
            chunks = compile_week_profile(service.data[SERVICE_CONF_WEEK_PROFILE])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        matching_entries: list[tuple[MaxCulConfigEntry, int]] = []
        matching_device_found = False
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            entry_path = entry.data.get(CONF_DEVICE_PATH)
            if (
                normalized_service_path is not None
                and (
                    not entry_path
                    or normalize_device_path(entry_path) != normalized_service_path
                )
            ):
                continue

            known_devices = entry.data.get(CONF_DEVICES) or {}
            candidates = _find_paired_device_candidates(
                known_devices, device_identifier
            )
            for device_id, device in candidates:
                matching_device_found = True
                device_type = device.get(CONF_TYPE)
                if not (
                    isinstance(device_type, str)
                    and "THERMOSTAT" in device_type.upper()
                ):
                    continue
                try:
                    numeric_device_id = int(device_id)
                except ValueError as err:
                    raise ServiceValidationError(
                        f"Invalid stored MAX! device address {device_id}"
                    ) from err
                if not 1 <= numeric_device_id <= 0xFFFFFF:
                    raise ServiceValidationError(
                        f"Invalid stored MAX! device address {device_id}"
                    )
                matching_entries.append((entry, numeric_device_id))

        if len(matching_entries) > 1:
            raise ServiceValidationError(
                "Thermostat identifier matches multiple paired devices or connections; "
                "use its hexadecimal address and specify device_path if needed"
            )
        if not matching_entries:
            if matching_device_found:
                raise ServiceValidationError(
                    f"Device {device_identifier} is not a supported thermostat"
                )
            raise ServiceValidationError(
                f"No loaded MaxCUL thermostat found for device {device_identifier}"
            )

        entry, numeric_device_id = matching_entries[0]
        request_id = uuid4().hex
        profile = service.data[SERVICE_CONF_WEEK_PROFILE]
        _store_week_profile_state(
            hass, entry, numeric_device_id, profile, request_id, "pending"
        )
        try:
            entry.runtime_data.set_week_profile(
                numeric_device_id, chunks, request_id
            )
        except HomeAssistantError:
            _store_week_profile_state(
                hass, entry, numeric_device_id, profile, request_id, "failed"
            )
            raise

    @callback
    def _service_associate(service: ServiceCall) -> None:
        _service_change_association(service, associate=True)

    @callback
    def _service_deassociate(service: ServiceCall) -> None:
        _service_change_association(service, associate=False)

    @callback
    def _week_profile_status_changed(payload: dict[str, Any]) -> None:
        if not payload.get("status_update"):
            return
        device_id = str(payload[ATTR_DEVICE_ID])
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            entry_path = entry.data.get(CONF_DEVICE_PATH)
            if (
                not entry_path
                or normalize_device_path(entry_path)
                != normalize_device_path(payload[ATTR_CONNECTION_DEVICE_PATH])
            ):
                continue
            profiles = entry.data.get(CONF_WEEK_PROFILES) or {}
            profile_state = profiles.get(device_id)
            if (
                not isinstance(profile_state, dict)
                or profile_state.get("request_id") != payload["request_id"]
            ):
                continue
            _store_week_profile_state(
                hass,
                entry,
                int(device_id),
                profile_state["profile"],
                payload["request_id"],
                payload["status"],
            )
            break

    def _service_change_association(
        service: ServiceCall, *, associate: bool
    ) -> None:
        thermostat_identifier = service.data[SERVICE_CONF_THERMOSTAT_ID]
        window_contact_identifier = service.data[SERVICE_CONF_WINDOW_CONTACT_ID]
        thermostat_entity_id = _resolve_association_entity(
            hass, thermostat_identifier, "climate"
        )
        window_contact_entity_id = _resolve_association_entity(
            hass, window_contact_identifier, "binary_sensor"
        )
        if thermostat_entity_id is not None:
            thermostat_identifier = thermostat_entity_id
        if window_contact_entity_id is not None:
            window_contact_identifier = window_contact_entity_id

        service_device_path = service.data.get(SERVICE_CONF_DEVICE_PATH)
        normalized_service_path = (
            normalize_device_path(service_device_path)
            if service_device_path
            else None
        )

        matching_entries = []
        unsupported_thermostat = False
        unsupported_window_contact = False
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            entry_path = entry.data.get(CONF_DEVICE_PATH)
            if (
                normalized_service_path is not None
                and (
                    not entry_path
                    or normalize_device_path(entry_path) != normalized_service_path
                )
            ):
                continue

            known_devices = entry.data.get(CONF_DEVICES) or {}
            thermostats = _find_paired_device_candidates(
                known_devices, thermostat_identifier
            )
            window_contacts = _find_paired_device_candidates(
                known_devices, window_contact_identifier
            )
            if not thermostats or not window_contacts:
                continue

            for thermostat_id, thermostat in thermostats:
                thermostat_protocol_type = _association_thermostat_type(
                    thermostat.get(CONF_TYPE)
                )
                if thermostat_protocol_type is None:
                    unsupported_thermostat = True
                    continue
                for window_contact_id, window_contact in window_contacts:
                    if not _is_window_contact_type(window_contact.get(CONF_TYPE)):
                        unsupported_window_contact = True
                        continue
                    try:
                        numeric_thermostat_id = int(thermostat_id)
                        numeric_window_contact_id = int(window_contact_id)
                    except ValueError as err:
                        raise ServiceValidationError(
                            "A paired MAX! device has an invalid stored address"
                        ) from err

                    if any(
                        device_id < 1 or device_id > 0xFFFFFF
                        for device_id in (
                            numeric_thermostat_id,
                            numeric_window_contact_id,
                        )
                    ):
                        raise ServiceValidationError(
                            "MAX! device addresses must be between 000001 and FFFFFF"
                        )
                    if numeric_thermostat_id == numeric_window_contact_id:
                        continue
                    matching_entries.append(
                        (
                            entry,
                            numeric_thermostat_id,
                            thermostat_protocol_type,
                            numeric_window_contact_id,
                        )
                    )

        if len(matching_entries) > 1:
            raise ServiceValidationError(
                "Device identifiers match multiple paired devices or connections; "
                "use hexadecimal addresses and specify device_path if needed"
            )
        if not matching_entries:
            if unsupported_thermostat:
                raise ServiceValidationError(
                    f"{thermostat_identifier} is not a supported heating thermostat"
                )
            if unsupported_window_contact:
                raise ServiceValidationError(
                    f"{window_contact_identifier} is not a supported window contact"
                )
            raise ServiceValidationError(
                "Could not find both paired devices on the same loaded MaxCUL connection"
            )

        (
            entry,
            numeric_thermostat_id,
            thermostat_protocol_type,
            numeric_window_contact_id,
        ) = matching_entries[0]
        entry.runtime_data.set_device_association(
            numeric_thermostat_id,
            thermostat_protocol_type,
            numeric_window_contact_id,
            associate=associate,
        )

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}/week-profile-card.js",
                str(Path(__file__).parent / "www" / "week-profile-card.js"),
                cache_headers=False,
            )
        ]
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ENABLE_PAIRING,
        _service_enable_pairing,
        schema=ENABLE_PAIRING_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WEEK_PROFILE,
        _service_set_week_profile,
        schema=SET_WEEK_PROFILE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ASSOCIATE,
        _service_associate,
        schema=DEVICE_ASSOCIATION_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DEASSOCIATE,
        _service_deassociate,
        schema=DEVICE_ASSOCIATION_SERVICE_SCHEMA,
    )
    async_dispatcher_connect(
        hass, SIGNAL_WEEK_PROFILE_UPDATE, _week_profile_status_changed
    )

    return True


def _association_thermostat_type(device_type: object) -> str | None:
    """Return a MAX! protocol type for a supported thermostat model."""
    if not isinstance(device_type, str):
        return None
    normalized = "".join(char for char in device_type.casefold() if char.isalnum())
    return {
        "heatingthermostat": HEATING_THERMOSTAT,
        "heatingthermostatplus": HEATING_THERMOSTAT_PLUS,
        "wallmountedthermostat": WALL_MOUNTED_THERMOSTAT,
        "wallthermostatplus": WALL_MOUNTED_THERMOSTAT,
    }.get(normalized)


def _is_window_contact_type(device_type: object) -> bool:
    """Return True for a MAX! shutter/window contact."""
    if not isinstance(device_type, str):
        return False
    normalized = "".join(char for char in device_type.casefold() if char.isalnum())
    return normalized in {"shuttercontact", "windowcontact", "windowshuttercontact"}


async def async_setup_entry(
    hass: HomeAssistant, config_entry: MaxCulConfigEntry
) -> bool:
    """Set up MaxCUL from a config entry."""
    device_path: str = config_entry.data[CONF_DEVICE_PATH]
    sender_id = config_entry.options.get(CONF_SENDER_ID)

    connection = MaxCulConnection(
        hass,
        device_path=device_path,
        sender_id=sender_id,
    )
    connection.start()

    config_entry.runtime_data = connection

    # Remove devices from the registry that are no longer part of the entry.
    known_devices = config_entry.data.get(CONF_DEVICES) or {}
    known_device_ids = {str(device_id) for device_id in known_devices}
    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    ):
        if any(
            identifier_domain == DOMAIN and device_id not in known_device_ids
            for identifier_domain, device_id in device_entry.identifiers
        ):
            device_registry.async_update_device(
                device_entry.id,
                remove_config_entry_id=config_entry.entry_id,
            )

    try:
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        # Do not leave the worker thread running if a platform fails to load.
        try:
            await hass.async_add_executor_job(connection.stop)
        except Exception:
            LOGGER.exception("Failed to stop MaxCUL connection after setup failure")
        raise

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: MaxCulConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if unload_ok:
        # Stopping joins the worker thread, so keep it off the event loop.
        await hass.async_add_executor_job(config_entry.runtime_data.stop)

    return unload_ok


class MaxCulConnection:
    """Wrapper around the maxcul connection thread."""

    def __init__(
        self, hass: HomeAssistant, device_path: str, sender_id: int | None = None
    ) -> None:
        self._hass = hass
        self._device_path = device_path

        if sender_id is None:
            sender_id = 0x123456

        self._connection = MaxConnection(
            device_path=device_path,
            callback=self._callback,
            sender_id=sender_id,
        )
        self._week_profile_requests: dict[str, _WeekProfileRequest] = {}
        self._week_profile_counters: dict[int, str] = {}
        original_handle_message = self._connection._handle_message
        original_resend_message = self._connection._resend_message

        def handle_message(message, signal_strength) -> None:
            original_handle_message(message, signal_strength)
            if isinstance(message, AckMessage):
                self._handle_week_profile_ack(message)

        def resend_message() -> None:
            original_resend_message()
            self._check_week_profile_timeouts()

        self._connection._handle_message = handle_message
        self._connection._resend_message = resend_message

    def start(self) -> None:
        """Start the connection thread."""
        self._connection.start()

    def stop(self) -> None:
        """Stop the connection thread."""
        self._connection.stop()

    def _callback(self, event, payload) -> None:
        """Handle events from the connection thread (not the event loop).

        dispatcher_send is thread-safe and may be used from here.
        """
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

        elif event == EVENT_WEEK_PROFILE_UPDATE:
            payload[ATTR_CONNECTION_DEVICE_PATH] = self._device_path
            payload["status_update"] = True
            dispatcher_send(self._hass, SIGNAL_WEEK_PROFILE_UPDATE, payload)

    def _emit_week_profile_status(
        self, device_id: int, request_id: str, status: str
    ) -> None:
        """Publish the state of a queued weekly-profile request."""
        self._callback(
            EVENT_WEEK_PROFILE_UPDATE,
            {
                ATTR_DEVICE_ID: device_id,
                "request_id": request_id,
                "status": status,
            },
        )

    def _handle_week_profile_ack(self, message: AckMessage) -> None:
        request_id = self._week_profile_counters.get(message.counter)
        if request_id is None:
            return

        request = self._week_profile_requests.get(request_id)
        if request is None or message.sender_id != request.device_id:
            return

        self._week_profile_counters.pop(message.counter, None)
        request.pending_counters.discard(message.counter)
        if message.state != "ok":
            request.failed = True
        if request.ready and request.failed:
            self._finish_week_profile(request_id, "failed")
        elif request.ready and not request.pending_counters:
            self._finish_week_profile(request_id, "acknowledged")

    def _check_week_profile_timeouts(self) -> None:
        outstanding = self._connection._outstanding_acks
        for request_id, request in tuple(self._week_profile_requests.items()):
            if request.ready and any(
                counter not in outstanding
                for counter in request.pending_counters
            ):
                self._finish_week_profile(request_id, "failed")

    def _finish_week_profile(self, request_id: str, status: str) -> None:
        request = self._week_profile_requests.pop(request_id, None)
        if request is None:
            return
        for counter in request.pending_counters:
            self._week_profile_counters.pop(counter, None)
        self._emit_week_profile_status(request.device_id, request_id, status)

    def enable_pairing(self, duration: int) -> None:
        """Enable pairing of devices."""
        LOGGER.debug("Enabling pairing on %s for %s s", self._device_path, duration)
        self._connection.enable_pairing(duration)

    def add_paired_device(self, device_id: int) -> None:
        """Add a device id to the paired devices."""
        LOGGER.debug("Adding device %s", device_id)
        self._connection.add_paired_device(device_id)

    def set_temperature(
        self, device_id: int, target_temperature: float, mode
    ) -> None:
        """Set the target temperature of a thermostat device."""
        LOGGER.debug(
            "Setting temperature on %s to %s (mode: %s)",
            device_id,
            target_temperature,
            mode,
        )
        self._connection.set_temperature(device_id, target_temperature, mode)

    def set_week_profile(
        self, device_id: int, chunks: list[WeekProfileChunk], request_id: str
    ) -> None:
        """Send an encoded week profile directly to a thermostat."""
        request = _WeekProfileRequest(device_id)
        self._week_profile_requests[request_id] = request
        for chunk in chunks:
            message = ConfigWeekProfileMessage(
                counter=self._connection._next_counter(),
                sender_id=self._connection.sender_id,
                receiver_id=device_id,
            )
            message.encode_payload = lambda payload=chunk.payload: payload
            request.pending_counters.add(message.counter)
            self._week_profile_counters[message.counter] = request_id
            if not self._connection._send_message(message):
                self._finish_week_profile(request_id, "failed")
                raise HomeAssistantError(
                    f"Could not queue week profile for MAX! device {device_id}"
                )
            self._connection._await_ack(message)
        request.ready = True
        if request.failed:
            self._finish_week_profile(request_id, "failed")
        elif not request.pending_counters:
            self._finish_week_profile(request_id, "acknowledged")

    def set_device_association(
        self,
        thermostat_id: int,
        thermostat_type: str,
        window_contact_id: int,
        *,
        associate: bool,
    ) -> None:
        """Create or remove the two MAX! peer links for a thermostat/contact pair."""
        message_type = AddLinkPartnerMessage if associate else RemoveLinkPartnerMessage
        links = (
            (
                thermostat_id,
                window_contact_id,
                SHUTTER_CONTACT,
            ),
            (
                window_contact_id,
                thermostat_id,
                thermostat_type,
            ),
        )

        for device_id, partner_id, partner_type in links:
            partner_address: int | str = (
                partner_id
                if associate
                else f"{partner_id:06X}"
            )
            message = message_type(
                counter=self._connection._next_counter(),
                sender_id=self._connection.sender_id,
                receiver_id=device_id,
                assocDevice=partner_address,
                assocDeviceType=partner_type,
            )
            if not associate:
                # pymaxcul's RemoveLinkPartnerMessage encoder uses DEVICE_TYPES
                # in the wrong direction, so provide the valid wire payload.
                payload = (
                    f"{partner_id:06X}{DEVICE_TYPES_BY_NAME[partner_type]:02X}"
                )
                message.encode_payload = lambda payload=payload: payload
            if not self._connection._send_message(message):
                operation = "associate" if associate else "deassociate"
                raise HomeAssistantError(
                    f"Could not {operation} MAX! devices {thermostat_id} "
                    f"and {window_contact_id}; the operation may be partial"
                )
            self._connection._await_ack(message)
