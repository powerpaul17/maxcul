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
    PRESET_NONE,
)

from homeassistant.components.maxcube.climate import (
    ATTR_VALVE_POSITION,
)

from homeassistant.config_entries import ConfigEntry

from homeassistant.const import (
    CONF_DEVICES,
    CONF_NAME,
    CONF_TYPE,
    TEMP_CELSIUS
)

from homeassistant.core import (
    HomeAssistant,
)

from custom_components.maxcul import (
    CONF_CONNECTIONS,
    CONF_DEVICE_PATH,
    DOMAIN,
    MaxCulConnection
)

from custom_components.maxcul.pymaxcul.maxcul._const import (
    HEATING_THERMOSTAT
)

from custom_components.maxcul.pymaxcul.maxcul import (
    ATTR_BATTERY_LOW,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_TEMPORARY,
)

MIN_TEMPERATURE = 5.0
MAX_TEMPERATURE = 30.0


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices):
    device_path = config_entry.data.get(CONF_DEVICE_PATH)
    connection = hass.data[DOMAIN][CONF_CONNECTIONS][device_path]
    devices = [
        MaxThermostat(connection, device_id, device[CONF_NAME])
        for device_id, device in config_entry.data.get(CONF_DEVICES).items()
        if device[CONF_TYPE] == HEATING_THERMOSTAT
    ]
    async_add_devices(devices)


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
        self._battery_low = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._device_id

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
        # TODO
        return PRESET_NONE

    @property
    def preset_modes(self) -> list[str] or None:
        return [
            PRESET_NONE,
        ]

    @property
    def hvac_action(self) -> str:
        if self._valve_position > 0:
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
            ATTR_VALVE_POSITION: self._valve_position,
            ATTR_BATTERY_LOW: self._battery_low
        }

    @staticmethod
    def _mode_to_hvac_mode(mode):
        return {
            MODE_AUTO: HVAC_MODE_AUTO,
            MODE_MANUAL: HVAC_MODE_HEAT,
            MODE_BOOST: HVAC_MODE_AUTO, # ?
            MODE_TEMPORARY: HVAC_MODE_HEAT # ? vacation, away mode
        }.get(mode)
