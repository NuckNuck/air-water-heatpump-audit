"""Wärme aus Durchfluss × Spreizung und Mindestleistung laut Datenblatt."""

from __future__ import annotations

from .series import Interval, Series, combine, weighted_values

# ρ·cp von Wasser bei ≈ 35 °C: 0,994 kg/l × 4,178 kJ/(kg·K). Fehler gegenüber 20-°C-Werten < 0,5 %
# (research_efficiency.md 4.4).
RHO_CP_KJ_PER_L_K = 4.153

CapacityTable = dict[float, dict[float, float]]  # Vorlauf °C → {Außentemperatur °C: Mindestleistung kW}


def heat_power(flow_rate: Series, flow: Series, ret: Series, start: float, end: float,
               offset_k: float = 0.0) -> Series:
    """Wärmeleistung in kW. Negativ bei Abtauung (Wärme wird dem Heizkreis entzogen und abgezogen).

    offset_k: Fühler-Offset Vorlauf − Rücklauf aus D4, wird von der Spreizung abgezogen.
    """
    dt = combine(flow, ret, lambda a, b: float(a) - float(b) - offset_k, start, end)
    return combine(flow_rate, dt, lambda q, d: float(q) / 60 * d * RHO_CP_KJ_PER_L_K, start, end)


def energy_kwh(power: Series, intervals: list[Interval]) -> float:
    """Integral einer Leistungs-Zeitreihe (kW) über die Intervalle, in kWh."""
    return sum(float(v) * w for v, w in weighted_values(power, intervals)) / 3600


def _interp(points: dict[float, float], x: float) -> float:
    xs = sorted(points)
    if x <= xs[0]:
        return points[xs[0]]
    if x >= xs[-1]:
        return points[xs[-1]]
    for a, b in zip(xs, xs[1:]):
        if a <= x <= b:
            return points[a] + (points[b] - points[a]) * (x - a) / (b - a)
    raise ValueError(x)


def parse_capacity_table(raw: object) -> CapacityTable | None:
    """Stammdatum `capacity_min_table` prüfen und in Zahlen wandeln (JSON-Speicher macht Schlüssel zu Text).

    Leer → None. Ungültig → ValueError mit deutschem Grund.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Erwartet: Vorlauftemperatur → {Außentemperatur: kW}.")
    table: CapacityTable = {}
    try:
        for flow, row in raw.items():
            if not isinstance(row, dict) or not row:
                raise ValueError(f"Zu Vorlauf {flow} fehlen die Außentemperaturen.")
            table[float(flow)] = {float(t): float(kw) for t, kw in row.items()}
    except (TypeError, ValueError) as err:
        raise ValueError(str(err) if "Vorlauf" in str(err) else "Alle Werte müssen Zahlen sein.") from err
    if any(kw <= 0 for row in table.values() for kw in row.values()):
        raise ValueError("Leistungen müssen größer als 0 kW sein.")
    return table


def min_capacity_kw(outdoor_c: float, flow_c: float, table: CapacityTable) -> float:
    """Mindestleistung, linear interpoliert nach Außentemperatur und Vorlauf; außerhalb der Tabelle der Randwert."""
    by_flow = {f: _interp(row, outdoor_c) for f, row in table.items()}
    return _interp(by_flow, flow_c)


def time_mean(series: Series, intervals: list[Interval]) -> float | None:
    pairs = weighted_values(series, intervals)
    w = sum(d for _, d in pairs)
    return sum(float(v) * d for v, d in pairs) / w if w else None
