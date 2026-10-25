import logging
from typing import Any, Mapping

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
)
from homeassistant.components.maxcube.climate import ATTR_VALVE_POSITION
from homeassistant.const import ATTR_MODE, ATTR_TEMPERATURE, UnitOfTemperature

from homeassistant.core import callback

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from maxcul._const import ATTR_DEVICE_ID
from maxcul import (
    ATTR_DESIRED_TEMPERATURE,
    ATTR_MEASURED_TEMPERATURE,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_TEMPORARY,
    MIN_TEMPERATURE as OFF_TEMPERATURE,
)

from . import (
    ATTR_CONNECTION_DEVICE_PATH,
    DOMAIN,
    SIGNAL_THERMOSTAT_UPDATE,
    SIGNAL_WEEK_PROFILE_UPDATE,
    MaxCulConnection,
)
from .const import DEFAULT_TEMPERATURE, MAX_TEMPERATURE, MIN_TEMPERATURE

LOGGER = logging.getLogger(__name__)


class MaxThermostat(ClimateEntity):
    """Climate entity for a Max! thermostat."""

    _attr_icon = "mdi:home-thermometer"

    def __init__(
        self,
        connection: MaxCulConnection,
        device_id: str,
        name: str,
        device_path: str,
        profile_state: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._device_id = device_id
        self._connection = connection
        self._device_path = device_path
        self._week_profile = (
            profile_state.get("profile") if isinstance(profile_state, dict) else None
        )
        self._week_profile_status = (
            profile_state.get("status") if isinstance(profile_state, dict) else None
        )
        self._week_profile_request_id = (
            profile_state.get("request_id")
            if isinstance(profile_state, dict)
            else None
        )

        self._current_temperature: float | None = None
        self._target_temperature: float | None = None
        self._valve_position: int | None = None

        self._desired_target_temperature: float | None = None

        self._mode: str | None = None
        self._desired_mode: str | None = None

        self._connection.add_paired_device(self.sender_id)

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self.name,
            "manufacturer": "eQ-3 / MAX!",
            "model": "Thermostat",
            "configuration_url": "https://github.com/powerpaul17/maxcul",
        }

    async def async_added_to_hass(self) -> None:
        @callback
        def update(payload: dict[str, Any]) -> None:
            device_id = payload.get(ATTR_DEVICE_ID)
            if device_id != self.sender_id:
                return

            current_temperature = payload.get(ATTR_MEASURED_TEMPERATURE)
            target_temperature = payload.get(ATTR_DESIRED_TEMPERATURE)
            valve_position = payload.get(ATTR_VALVE_POSITION)
            mode = payload.get(ATTR_MODE)

            LOGGER.debug(
                "Received update of %s (%x): current_temperature: %s, "
                "target_temperature: %s, valve_position: %s, mode: %s",
                self.name,
                self.sender_id,
                current_temperature,
                target_temperature,
                valve_position,
                mode,
            )

            if current_temperature is not None:
                self._current_temperature = current_temperature

            if target_temperature is not None:
                self._target_temperature = target_temperature

            if valve_position is not None:
                self._valve_position = valve_position

            if mode is not None:
                self._mode = mode

            self._desired_target_temperature = None
            self._desired_mode = None

            self.async_schedule_update_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_THERMOSTAT_UPDATE, update)
        )

        @callback
        def week_profile_update(payload: dict[str, Any]) -> None:
            if (
                payload.get("device_id") != self._device_id
                or payload.get(ATTR_CONNECTION_DEVICE_PATH) != self._device_path
            ):
                return
            if (
                "profile" not in payload
                and payload.get("request_id") != self._week_profile_request_id
            ):
                return
            self._week_profile = payload.get("profile", self._week_profile)
            self._week_profile_status = payload.get(
                "status", self._week_profile_status
            )
            self._week_profile_request_id = payload.get(
                "request_id", self._week_profile_request_id
            )
            self.async_schedule_update_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_WEEK_PROFILE_UPDATE, week_profile_update
            )
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def sender_id(self) -> int:
        ''' Return the RF address of the device '''
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def supported_features(self) -> ClimateEntityFeature:
        return ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def min_temp(self) -> float:
        return MIN_TEMPERATURE

    @property
    def max_temp(self) -> float:
        return MAX_TEMPERATURE

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        return self._current_temperature

    @property
    def target_temperature(self) -> float | None:
        target_temperature = self._target_temperature

        if (
            target_temperature is None
            or target_temperature < self.min_temp
            or target_temperature > self.max_temp
        ):
            return None

        return target_temperature

    @property
    def target_temperature_step(self) -> float:
        return 0.5

    @property
    def preset_mode(self) -> str | None:
        if self._mode == MODE_BOOST:
            return PRESET_BOOST
        if self._mode == MODE_TEMPORARY:
            return PRESET_AWAY
        return PRESET_NONE

    @property
    def preset_modes(self) -> list[str]:
        return [PRESET_NONE, PRESET_AWAY, PRESET_BOOST]

    @property
    def hvac_action(self) -> HVACAction:
        if self._valve_position is not None and self._valve_position > 0:
            return HVACAction.HEATING

        return (
            HVACAction.OFF if self.hvac_mode == HVACMode.OFF else HVACAction.IDLE
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._mode == MODE_MANUAL and self._target_temperature == OFF_TEMPERATURE:
            return HVACMode.OFF
        return self._mode_to_hvac_mode(self._mode)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        attributes = {
            ATTR_VALVE_POSITION: self._valve_position,
            "maxcul_device_id": self._device_id,
            "maxcul_device_name": self._name,
        }
        if self._week_profile is not None:
            attributes["maxcul_week_profile"] = self._week_profile
            attributes["maxcul_week_profile_status"] = self._week_profile_status
            attributes["maxcul_week_profile_request_id"] = (
                self._week_profile_request_id
            )
        return attributes

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        new_temperature = (
            self._desired_target_temperature
            if self._desired_target_temperature is not None
            else self._target_temperature
            if self._target_temperature is not None
            else DEFAULT_TEMPERATURE
        )
        new_hvac_mode = self._hvac_mode_to_mode(hvac_mode)
        if new_hvac_mode is None:
            raise ValueError(f"Unsupported HVAC mode {hvac_mode}")

        LOGGER.debug(
            "Setting HVAC mode of %s (%x) to %s (%.1f)",
            self.name,
            self.sender_id,
            new_hvac_mode,
            new_temperature,
        )

        if hvac_mode == HVACMode.OFF:
            # Set desired temperature to absolute minimum
            new_temperature = self._desired_target_temperature = OFF_TEMPERATURE

        if hvac_mode == HVACMode.HEAT:
            # Avoid retaining the protocol's off sentinel after switching to heat.
            if new_temperature == OFF_TEMPERATURE:
                new_temperature = self._desired_target_temperature = DEFAULT_TEMPERATURE

        self._desired_mode = new_hvac_mode

        self._connection.set_temperature(
            self.sender_id,
            new_temperature,
            new_hvac_mode,
        )

    def set_temperature(self, **kwargs: Any) -> None:
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            raise ValueError(
                f"No {ATTR_TEMPERATURE} parameter passed to set_temperature method."
            )

        hvac_mode = self._desired_mode or self._mode or MODE_MANUAL

        hvac_mode_from_args = self._hvac_mode_to_mode(kwargs.get(ATTR_HVAC_MODE))
        if hvac_mode_from_args and hvac_mode_from_args != hvac_mode:
            hvac_mode = self._desired_mode = hvac_mode_from_args

        LOGGER.debug(
            "Setting temperature of %s (%x) to %.1f with mode %s",
            self.name,
            self.sender_id,
            target_temperature,
            hvac_mode,
        )

        self._desired_target_temperature = target_temperature

        self._connection.set_temperature(
            self.sender_id,
            target_temperature,
            hvac_mode,
        )

    def set_preset_mode(self, preset_mode: str) -> None:
        LOGGER.debug(
            'Setting preset mode of %s (%x) to %s',
            self.name,
            self.sender_id,
            preset_mode
        )

        target_temperature = (
            self._desired_target_temperature
            if self._desired_target_temperature is not None
            else self._target_temperature
            if self._target_temperature is not None
            else DEFAULT_TEMPERATURE
        )

        if preset_mode == PRESET_NONE:
            mode = MODE_MANUAL

        elif preset_mode == PRESET_AWAY:
            mode = MODE_TEMPORARY

        elif preset_mode == PRESET_BOOST:
            mode = MODE_BOOST

        else:
            raise ValueError(f"Unsupported preset mode {preset_mode}")

        self._desired_mode = mode

        self._connection.set_temperature(
            self.sender_id,
            target_temperature,
            mode,
        )

    @staticmethod
    def _hvac_mode_to_mode(hvac_mode: HVACMode | None) -> str | None:
        return {
            HVACMode.OFF: MODE_MANUAL,
            HVACMode.AUTO: MODE_AUTO,
            HVACMode.HEAT: MODE_MANUAL
        }.get(hvac_mode)

    @staticmethod
    def _mode_to_hvac_mode(mode: str | None) -> HVACMode | None:
        return {
            MODE_AUTO: HVACMode.AUTO,
            MODE_MANUAL: HVACMode.HEAT,
            MODE_BOOST: HVACMode.AUTO,
            MODE_TEMPORARY: HVACMode.HEAT,
        }.get(mode)
