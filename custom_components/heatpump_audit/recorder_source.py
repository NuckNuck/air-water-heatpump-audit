"""Adapter HA-Recorder: Zustandsverlauf je Rolle als Zeitreihe [(t, v)] für audit_core.

Gleiche Semantik wie der InfluxDB-Adapter des Prototyps: Zahlen als float, on/off als 1/0, Text nur für Text-Rollen.
`unavailable`/`unknown` werden ausgelassen – der letzte gültige Wert gilt weiter, Lücken erkennt Audit 0 über den
Heartbeat. Läuft im Executor (Datenbankzugriff blockiert).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.recorder import history
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
