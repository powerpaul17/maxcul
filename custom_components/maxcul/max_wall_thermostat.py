"""Climate entity for a Max! Wall Thermostat+ device."""

from __future__ import annotations

from .max_thermostat import MaxThermostat


class MaxWallThermostat(MaxThermostat):
    """Climate entity for the Max! Wall Thermostat+ model."""

    _attr_icon = "mdi:radiator"
