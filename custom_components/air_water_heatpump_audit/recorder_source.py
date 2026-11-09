"""Adapter HA-Recorder: Zustandsverlauf je Rolle als Zeitreihe [(t, v)] für audit_core.

Gleiche Semantik wie der InfluxDB-Adapter des Prototyps: Zahlen als float, on/off als 1/0, Text nur für Text-Rollen.
`unavailable`/`unknown` werden ausgelassen – der letzte gültige Wert gilt weiter, Lücken erkennt Audit 0 über den
Heartbeat. Läuft im Executor (Datenbankzugriff blockiert).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.recorder import history, statistics
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State

from .audit_core.series import Series
from .const import TEXT_ROLES, WEATHER_ATTRIBUTE

_INVALID = (STATE_UNAVAILABLE, STATE_UNKNOWN, "", None)


def _value(role: str, state: State):
    if state.entity_id.startswith("weather."):  # LazyState aus dem Recorder hat kein .domain
        raw = state.attributes.get(WEATHER_ATTRIBUTE)
    else:
        raw = state.state
    if raw in _INVALID:
        return None
    if role in TEXT_ROLES:
        return raw
    if raw == STATE_ON:
        return 1.0
    if raw == STATE_OFF:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def to_series(role: str, states: list[State]) -> Series:
    out: Series = []
    for st in states:
        v = _value(role, st)
        if v is not None:
            out.append((st.last_updated_timestamp, v))
    return out


def load_series(hass: HomeAssistant, roles: dict[str, str], start: datetime, end: datetime) -> dict[str, Series]:
    """Alle Zustandswechsel (nicht nur „signifikante“) inklusive des zu `start` gültigen Zustands."""
    with_attrs = {r: e for r, e in roles.items() if e.startswith("weather.")}
    plain = {r: e for r, e in roles.items() if r not in with_attrs}
    out: dict[str, Series] = {}
    for group, no_attributes in ((plain, True), (with_attrs, False)):
        if not group:
            continue
        found = history.get_significant_states(hass, start, end, list(set(group.values())),
                                               significant_changes_only=False, no_attributes=no_attributes)
        for role, eid in group.items():
            out[role] = to_series(role, found.get(eid, []))
    return out


# Statistik-Tage (Spezifikation 1.11): Rolle → (Schlüssel im Kern, Art des Tageswerts)
STATISTIC_ROLES = {"electricity_meter": ("electricity_kwh", "change"),
                   "controller_heat_today": ("controller_heat_kwh", "change")}
OUTDOOR_ROLES = ("outdoor_temp_reference", "outdoor_temp")  # Tagesmittel, Wetterdienst bevorzugt
STATISTIC_UNITS = {"energy": "kWh", "temperature": "°C"}


def load_statistics(hass: HomeAssistant, roles: dict[str, str], start: datetime, end: datetime,
                    label) -> dict[str, dict[str, float]] | None:
    """Tageswerte der Langzeitstatistik je Rolle als {Kern-Schlüssel: {Tag: Wert}}; Tag = label(Tagesbeginn).

    Strom und Steuerungswärme als Änderung je Tag (Summenstatistik), Außentemperatur als Tagesmittel. None, wenn
    Strom oder Steuerungswärme keine Statistik haben (dann gibt es keine Statistik-Tage). Läuft im Executor."""
    wanted = {role: (key, kind) for role, (key, kind) in STATISTIC_ROLES.items() if role in roles}
    outdoor = next((r for r in OUTDOOR_ROLES if roles.get(r, "").startswith("sensor.")), None)
    if outdoor:
        wanted[outdoor] = ("outdoor_mean", "mean")
    if not all(r in wanted for r in STATISTIC_ROLES):
        return None
    found = statistics.statistics_during_period(hass, start, end, {roles[r] for r in wanted}, "day",
                                                STATISTIC_UNITS, {"change", "mean"})
    out: dict[str, dict[str, float]] = {}
    for role, (key, kind) in wanted.items():
        out[key] = {label(row["start"]): float(row[kind]) for row in found.get(roles[role], [])
                    if row.get(kind) is not None}
    return out if all(out.get(STATISTIC_ROLES[r][0]) for r in STATISTIC_ROLES) else None
