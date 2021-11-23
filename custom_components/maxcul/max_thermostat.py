from typing import Any, Mapping

from homeassistant.components.climate import (
    ClimateEntity,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_PRESET_MODE
)

from homeassistant.components.climate.const import (
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    HVAC_MODE_AUTO,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
)

from homeassistant.components.maxcube.climate import (
    ATTR_VALVE_POSITION,
)

from homeassistant.const import (
    ATTR_MODE,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS
)

from homeassistant.core import callback

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from custom_components.maxcul import (
    DOMAIN,
    SIGNAL_THERMOSTAT_UPDATE,
    MaxCulConnection
)

from custom_components.maxcul.const import (
    MIN_TEMPERATURE,
    MAX_TEMPERATURE,
    DEFAULT_TEMPERATURE
)

from maxcul._const import (
    ATTR_DEVICE_ID
)

from maxcul import (
    ATTR_DESIRED_TEMPERATURE,
    ATTR_MEASURED_TEMPERATURE,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_TEMPORARY,
    MIN_TEMPERATURE as OFF_TEMPERATURE,
)


class MaxThermostat(ClimateEntity):

    def __init__(self, connection: MaxCulConnection, device_id: str, name: str):
        self._name = name
        self._device_id = device_id
        self._connection = connection

        self._current_temperature: float or None = None
        self._target_temperature: float or None = None
        self._valve_position: int or None = None

        # auto manual temporary boost
        self._mode = None

        self._connection.add_paired_device(self.sender_id)

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {
                (DOMAIN, self._device_id)
            },
            "name": self.name,
        }

    async def async_added_to_hass(self) -> None:
        @callback
        def update(payload):
            device_id = payload.get(ATTR_DEVICE_ID)
            if device_id != self.sender_id:
                return

            current_temperature = payload.get(ATTR_MEASURED_TEMPERATURE)
            target_temperature = payload.get(ATTR_DESIRED_TEMPERATURE)
            valve_position = payload.get(ATTR_VALVE_POSITION)
            mode = payload.get(ATTR_MODE)

            if current_temperature is not None:
                self._current_temperature = current_temperature

            if target_temperature is not None:
                self._target_temperature = target_temperature

            if valve_position is not None:
                self._valve_position = valve_position

            if mode is not None:
                self._mode = mode

            self.async_schedule_update_ha_state()

        async_dispatcher_connect(self.hass, SIGNAL_THERMOSTAT_UPDATE, update)

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def sender_id(self) -> int:
        return int(self._device_id)

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def supported_features(self) -> int:
        return SUPPORT_PRESET_MODE | SUPPORT_TARGET_TEMPERATURE

    @property
    def min_temp(self) -> float:
        return MIN_TEMPERATURE

    @property
    def max_temp(self) -> float:
        return MAX_TEMPERATURE

    @property
    def temperature_unit(self) -> str:
        return TEMP_CELSIUS

    @property
    def current_temperature(self) -> float or None:
        return self._current_temperature

    @property
    def target_temperature(self) -> float or None:
        return self._target_temperature

    @property
    def target_temperature_step(self) -> float:
        return 0.5

    @property
    def preset_mode(self) -> str or None:
        if self._mode == MODE_BOOST:
            return PRESET_BOOST
        if self._mode == MODE_TEMPORARY:
            return PRESET_AWAY

        if not self._target_temperature:
            return PRESET_NONE

        return PRESET_NONE

    @property
    def preset_modes(self) -> list[str] or None:
        return [
            PRESET_NONE,
            PRESET_AWAY,
            PRESET_BOOST
        ]

    @property
    def hvac_action(self) -> str:
        if self._valve_position is not None and self._valve_position > 0:
            return CURRENT_HVAC_HEAT

        return (
            CURRENT_HVAC_OFF if self.hvac_mode == HVAC_MODE_OFF else CURRENT_HVAC_IDLE
        )

    @property
    def hvac_mode(self) -> str:
        if self._mode == MODE_MANUAL and self._target_temperature == OFF_TEMPERATURE:
            return HVAC_MODE_OFF
        else:
            return self._mode_to_hvac_mode(self._mode)

    @property
    def hvac_modes(self) -> list[str]:
        return [
            HVAC_MODE_OFF,
            HVAC_MODE_AUTO,
            HVAC_MODE_HEAT
        ]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        return {
            ATTR_VALVE_POSITION: self._valve_position
        }

    def set_hvac_mode(self, hvac_mode: str) -> None:
        new_temperature = self._target_temperature or DEFAULT_TEMPERATURE

        new_hvac_mode = self._hvac_mode_to_mode(hvac_mode)
        if hvac_mode == HVAC_MODE_OFF:
            new_temperature = OFF_TEMPERATURE

        self._connection.set_temperature(
            self.sender_id,
            new_temperature,
            new_hvac_mode
        )

    def set_temperature(self, **kwargs) -> None:
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            raise ValueError(
                f"No {ATTR_TEMPERATURE} parameter passed to set_temperature method."
            )

        self._connection.set_temperature(
            self.sender_id,
            target_temperature,
            self._mode or MODE_MANUAL
        )

    def set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_NONE:
            self._connection.set_temperature(
                self.sender_id,
                self._target_temperature,
                MODE_MANUAL
            )

        elif preset_mode == PRESET_AWAY:
            self._connection.set_temperature(
                self.sender_id,
                self._target_temperature,
                MODE_TEMPORARY
            )

        elif preset_mode == PRESET_BOOST:
            self._connection.set_temperature(
                self.sender_id,
                self._target_temperature,
                MODE_BOOST
            )

        else:
            raise ValueError(f"Unsupported preset mode {preset_mode}")

    @staticmethod
    def _hvac_mode_to_mode(hvac_mode):
        return {
            HVAC_MODE_OFF: MODE_MANUAL,
            HVAC_MODE_AUTO: MODE_AUTO,
            HVAC_MODE_HEAT: MODE_MANUAL
        }.get(hvac_mode)

    @staticmethod
    def _mode_to_hvac_mode(mode):
        return {
            MODE_AUTO: HVAC_MODE_AUTO,
            MODE_MANUAL: HVAC_MODE_HEAT,
            MODE_BOOST: HVAC_MODE_AUTO, # ?
            MODE_TEMPORARY: HVAC_MODE_HEAT # ? vacation, away mode
        }.get(mode)