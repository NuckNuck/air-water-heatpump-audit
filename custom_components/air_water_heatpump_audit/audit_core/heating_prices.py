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
# - Holzpellets: 4,8 kWh/kg Heizwert (C.A.R.M.E.N., Steckbrief Holzpellets); Nutzungsgrad 0,80 als Mitte der
#   Feldmessungen an Pelletkesseln im Bestand: 65–85 % (Carlon et al. 2015, Applied Energy 155, n = 5), 70–85 %
#   (EIFER 2008–2010, n = 9; DBFZ/EIFER KombiOpt-Schlussbericht 2018, S. 7: 70–90 %).
# - Fernwärme und Stromdirektheizung: Preis je kWh gelieferter Wärme bzw. Strom, Nutzungsgrad 1.
SYSTEMS: dict[str, dict] = {
    "natural_gas": {"efficiency": 0.86, "kwh_per_l": None, "kwh_per_kg": None},
    "heating_oil": {"efficiency": 0.91, "kwh_per_l": 10.0, "kwh_per_kg": None},
    "wood_pellets": {"efficiency": 0.80, "kwh_per_l": None, "kwh_per_kg": 4.8},
    "district_heating": {"efficiency": 1.0, "kwh_per_l": None, "kwh_per_kg": None},
    "direct_electric": {"efficiency": 1.0, "kwh_per_l": None, "kwh_per_kg": None},
}
SOURCE_KINDS = ("official", "association", "commercial", "local")
NO_PREVIOUS_SYSTEM = "none"  # Stammdatum `previous_heating_system` bei einem Neubau

# Einheiten des früheren Jahresverbrauchs (so, wie er auf der Abrechnung steht) → (Faktor, Bezug: kwh | l | kg)
CONSUMPTION_UNITS = {"kWh": (1.0, "kwh"), "MWh": (1000.0, "kwh"), "L": (1.0, "l"), "kg": (1.0, "kg"),
                     "t": (1000.0, "kg")}

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


def efficiency(system: str, master: dict | None = None) -> float:
    """Nutzungsgrad eines Systems. Für das frühere Heizsystem gilt der Wert aus den Stammdaten (`reference_efficiency`),
    für alle anderen die Konstante aus SYSTEMS."""
    master = master or {}
    own = master.get("reference_efficiency")
    if own and system == master.get("previous_heating_system"):
        return float(own)
    return SYSTEMS[system]["efficiency"]


def heat_price_factor(system: str, unit: str | None, eff: float | None = None) -> float | None:
    """Faktor von „Preis in der Einheit des Sensors“ auf ct/kWh Wärme."""
    f = fuel_factor(system, unit)
    return None if f is None else 100 * f / (eff or SYSTEMS[system]["efficiency"])


def consumption_kwh(system: str | None, amount: float | None, unit: str | None) -> float | None:
    """Früherer Jahresverbrauch laut Abrechnung in kWh Brennstoff; None, wenn Menge, Einheit oder System fehlen oder
    die Einheit nicht zum System passt (z. B. Liter bei Gas)."""
    spec = SYSTEMS.get(system or "")
    unit_spec = CONSUMPTION_UNITS.get(unit or "")
    if spec is None or unit_spec is None or not amount:
        return None
    factor, basis = unit_spec
    if basis == "kwh":
        return float(amount) * factor
    kwh = spec["kwh_per_l"] if basis == "l" else spec["kwh_per_kg"]
    return float(amount) * factor * kwh if kwh else None


def usable(ref: dict) -> bool:
    return heat_price_factor(ref.get("system"), ref.get("unit")) is not None


def fixed_fee(ref: dict) -> float | None:
    """Feste Kosten eines Vergleichspreises in €/a, die noch über die Jahreswärme verteilt werden müssen. None, wenn der
    Preis sie schon enthält (`includes_fixed_charges`) oder keine angegeben sind."""
    if ref.get("includes_fixed_charges"):
        return None
    fee = ref.get("annual_base_fee")
    try:
        return float(fee) if fee not in (None, "") else None
    except (TypeError, ValueError):
        return None


def day_heat_price(ref: dict, series: Series, a: float, b: float, master: dict | None = None,
                   annual_heat_kwh: float | None = None) -> float | None:
    """Zeitmittel des Preises über den Tag [a, b) in ct/kWh Wärme; None ohne Preis an diesem Tag.

    Feste Kosten des Vergleichs (`annual_base_fee`) kommen als fester Aufschlag dazu: €/a ÷ Jahreswärme. Ohne
    Jahreswärme bleiben sie draußen; das steht dann in `meta`."""
    eff = efficiency(ref["system"], master)
    factor = heat_price_factor(ref["system"], ref["unit"], eff)
    mean = time_mean(series, [(a, b)]) if series and factor is not None else None
    if mean is None:
        return None
    price = mean * factor
    fee = fixed_fee(ref)
    if fee and annual_heat_kwh:
        price += 100 * fee / annual_heat_kwh
    return round(price, 1)


def meta(ref: dict, master: dict | None = None, annual_heat_kwh: float | None = None) -> dict:
    """Angaben für die Karte, ohne Zeitreihe. `fixed_charges`: `included` (im Preis), `added` (eingerechnet),
    `missing_heat` (angegeben, aber Jahreswärme unbekannt) oder None (keine Angabe)."""
    fee = fixed_fee(ref)
    fixed = ("included" if ref.get("includes_fixed_charges") else
             None if fee is None else "added" if annual_heat_kwh else "missing_heat")
    return {"id": ref["id"], "system": ref["system"], "name": ref.get("name") or ref["id"],
            "source": ref.get("source"), "source_kind": ref.get("source_kind"), "as_of": ref.get("as_of"),
            "efficiency": efficiency(ref["system"], master), "fixed_charges": fixed}
