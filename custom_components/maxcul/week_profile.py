"""MAX! thermostat week profile encoding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_DAY_IDS = {
    "sat": 0,
    "sun": 1,
    "mon": 2,
    "tue": 3,
    "wed": 4,
    "thu": 5,
    "fri": 6,
}
_DAY_NAMES = {
    "sat": "sat",
    "saturday": "sat",
    "sun": "sun",
    "sunday": "sun",
    "mon": "mon",
    "monday": "mon",
    "tue": "tue",
    "tuesday": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "thu": "thu",
    "thursday": "thu",
    "fri": "fri",
    "friday": "fri",
}
_DEFAULT_POINT = "4520"
_PROFILE_TIME = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass(frozen=True)
class WeekProfileChunk:
    """One MAX! ConfigWeekProfile payload."""

    day: int
    part: int
    payload: str


def compile_week_profile(profile: str) -> list[WeekProfileChunk]:
    """Validate and encode a complete, FHEM-style weekly thermostat profile.

    Each line has a day followed by alternating temperatures and switch times,
    for example ``Mon 21,06:00,17,22:00,16``.
    """
    schedules: dict[int, list[str]] = {}

    for raw_line in profile.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Ungültige Zeile '{line}': Tag und Profil erwartet.")

        day_name = _DAY_NAMES.get(parts[0].casefold())
        if day_name is None:
            raise ValueError(f"Unbekannter Wochentag '{parts[0]}'.")
        day = _DAY_IDS[day_name]
        if day in schedules:
            raise ValueError(f"Wochentag '{parts[0]}' wurde mehrfach angegeben.")

        tokens = [token.strip() for token in parts[1].split(",")]
        if any(not token for token in tokens) or len(tokens) % 2 == 0:
            raise ValueError(
                f"Ungültiges Profil für {parts[0]}: "
                "Temperatur und Schaltzeiten müssen abwechseln."
            )

        temperatures = [_encode_temperature(token) for token in tokens[::2]]
        if len(temperatures) > 13:
            raise ValueError(f"Zu viele Schaltpunkte für {parts[0]} (maximal 13).")

        end_times = [_parse_time(token) for token in tokens[1::2]]
        if any(
            end_time <= (end_times[index - 1] if index else 0)
            for index, end_time in enumerate(end_times)
        ):
            raise ValueError(
                f"Schaltzeiten für {parts[0]} müssen aufsteigend und vor 24:00 liegen."
            )

        points = []
        for index, temperature in enumerate(temperatures):
            end_time = end_times[index] if index < len(end_times) else 1440
            points.append(_encode_point(temperature, end_time))
        points.extend([_DEFAULT_POINT] * (13 - len(points)))
        schedules[day] = points

    missing_days = sorted(set(_DAY_IDS.values()) - schedules.keys())
    if missing_days:
        missing_names = ", ".join(
            name for name, day in _DAY_IDS.items() if day in missing_days
        )
        raise ValueError(f"Wochenprofil unvollständig; es fehlen: {missing_names}.")

    chunks: list[WeekProfileChunk] = []
    for day, points in sorted(schedules.items()):
        chunks.append(WeekProfileChunk(day, 0, f"{day:02x}{''.join(points[:7])}"))

        remaining_points = points[7:]
        if remaining_points != [_DEFAULT_POINT] * 6:
            chunks.append(
                WeekProfileChunk(
                    day,
                    1,
                    f"{day | 0x08:02x}{''.join(remaining_points)}",
                )
            )

    return chunks


def _encode_temperature(value: str) -> int:
    try:
        temperature = Decimal(value)
    except InvalidOperation as err:
        raise ValueError(f"Ungültige Temperatur '{value}'.") from err

    half_degrees = temperature * 2
    if (
        not temperature.is_finite()
        or temperature < Decimal("4.5")
        or temperature > Decimal("30.5")
        or half_degrees != half_degrees.to_integral_value()
    ):
        raise ValueError(
            f"Temperatur '{value}' muss zwischen 4,5 und 30,5 °C "
            "in 0,5-Grad-Schritten liegen."
        )
    return int(half_degrees)


def _parse_time(value: str) -> int:
    match = _PROFILE_TIME.fullmatch(value)
    if match is None:
        raise ValueError(f"Ungültige Uhrzeit '{value}'; erwartet wird HH:MM.")

    hour, minute = (int(part) for part in match.groups())
    if hour > 23 or minute > 59 or minute % 5:
        raise ValueError(
            f"Uhrzeit '{value}' muss vor 24:00 liegen und in 5-Minuten-Schritten sein."
        )
    return hour * 60 + minute


def _encode_point(temperature: int, end_time: int) -> str:
    time_slot = end_time // 5
    encoded_point = (temperature << 9) | time_slot
    return f"{encoded_point:04x}"
