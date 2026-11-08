"""Wärmepreise anderer Heizsysteme als Vergleich im Kosten-Zeitstrahl.

Das Audit holt keine Preise selbst. Sie kommen als Preis-Sensoren aus beliebigen Integrationen (Preis-Plugin,
Scrape, …), erkennbar am Attribut `heating_system`. Hier wird nur umgerechnet: Brennstoffpreis in der Einheit des
Sensors → €/kWh Brennstoff → ct/kWh Wärme über den Nutzungsgrad des Systems. Herstellerneutral und netzwerkfrei.
"""

from __future__ import annotations

from .heat import time_mean
from .series import Series

# Energieinhalt je Liefereinheit und Jahresnutzungsgrad, beides auf dieselbe Bezugsgröße.
# - Erdgas: abgerechnet in kWh nach Brennwert; Feldmittel Gas-Brennwertkessel 0,86 (DBU-Feldtest, 60 Anlagen),
#   wie der Vorgabewert von `reference_efficiency`.
# - Heizöl EL: 10 kWh/L Heizwert (Verbraucherzentrale, LfL); Nutzungsgrad wie Gas 0,86 auf den Brennwert, mit
#   Brennwert/Heizwert 1,06 → 0,91 auf den Heizwert.
# - Holzpellets: 4,8 kWh/kg Heizwert (C.A.R.M.E.N., Steckbrief Holzpellets); Nutzungsgrad 0,85 (Annahme
#   Pelletkessel im Bestand).
# - Fernwärme und Stromdirektheizung: Preis je kWh gelieferter Wärme bzw. Strom, Nutzungsgrad 1.
SYSTEMS: dict[str, dict] = {
    "natural_gas": {"efficiency": 0.86, "kwh_per_l": None, "kwh_per_kg": None},
    "heating_oil": {"efficiency": 0.91, "kwh_per_l": 10.0, "kwh_per_kg": None},
    "wood_pellets": {"efficiency": 0.85, "kwh_per_l": None, "kwh_per_kg": 4.8},
    "district_heating": {"efficiency": 1.0, "kwh_per_l": None, "kwh_per_kg": None},
    "direct_electric": {"efficiency": 1.0, "kwh_per_l": None, "kwh_per_kg": None},
}
SOURCE_KINDS = ("official", "association", "commercial", "local")

# Einheit (klein, ohne Leerzeichen, EUR = €) → (€ je Einheit-Faktor, Bezug: kwh | l | kg)
_UNITS = {
    "€/kwh": (1.0, "kwh"), "ct/kwh": (0.01, "kwh"), "€/mwh": (0.001, "kwh"),
    "€/l": (1.0, "l"), "ct/l": (0.01, "l"), "€/100l": (0.01, "l"), "€/1000l": (0.001, "l"),
    "€/kg": (1.0, "kg"), "€/t": (0.001, "kg"),
}


def _norm_unit(unit: str | None) -> str:
    return (unit or "").lower().replace(" ", "").replace("eur", "€").replace("cent", "ct")


def fuel_factor(system: str, unit: str | None) -> float | None:
    """Faktor von „Preis in der Einheit des Sensors“ auf €/kWh Brennstoff; None = Einheit passt nicht zum System."""
    spec = SYSTEMS.get(system)
    unit_spec = _UNITS.get(_norm_unit(unit))
    if spec is None or unit_spec is None:
        return None
    eur, basis = unit_spec
    if basis == "kwh":
        return eur
    kwh = spec["kwh_per_l"] if basis == "l" else spec["kwh_per_kg"]
    return eur / kwh if kwh else None


def heat_price_factor(system: str, unit: str | None) -> float | None:
    """Faktor von „Preis in der Einheit des Sensors“ auf ct/kWh Wärme."""
    f = fuel_factor(system, unit)
    return None if f is None else 100 * f / SYSTEMS[system]["efficiency"]


def usable(ref: dict) -> bool:
    return heat_price_factor(ref.get("system"), ref.get("unit")) is not None


def day_heat_price(ref: dict, series: Series, a: float, b: float) -> float | None:
    """Zeitmittel des Preises über den Tag [a, b) in ct/kWh Wärme; None ohne Preis an diesem Tag."""
    factor = heat_price_factor(ref["system"], ref["unit"])
    mean = time_mean(series, [(a, b)]) if series and factor is not None else None
    return None if mean is None else round(mean * factor, 1)


def meta(ref: dict) -> dict:
    """Angaben für die Karte, ohne Zeitreihe."""
    return {"id": ref["id"], "system": ref["system"], "name": ref.get("name") or ref["id"],
            "source": ref.get("source"), "source_kind": ref.get("source_kind"), "as_of": ref.get("as_of"),
            "efficiency": SYSTEMS[ref["system"]]["efficiency"]}
