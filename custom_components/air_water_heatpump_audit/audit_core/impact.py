"""Wirkung der Aktionen: Was bringt oder kostet eine Aktion im Jahr, und mit welcher anderen Prüfung steht sie im
Zielkonflikt? (Spezifikation 1.10)

Die Audits urteilen einzeln; hier kommen sie zusammen. Grundlage ist der Jahresstrom aus der Hochrechnung über die
Gradtage (wie K2) und der Warmwasserstrom aus den Ladungen. Jede Wirkung ist eine grobe Schätzung mit den
Faustwerten, die auch die Prüfungen nennen (2–3 % je Kelvin Vorlauf, 1,4 % je Kelvin Warmwasser); sie dient zum
Sortieren, nicht als Versprechen. Gerechnet wird nur aus Grundgrößen des Kontexts und dem eigenen Ergebnis, damit
ein Audit allein dieselbe Wirkung zeigt wie im Gesamtlauf.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property

from . import cost as k1
from . import dhw as w1
from . import flow_temp as t2
from .heat import RHO_CP_KJ_PER_L_K
from .result import HINT, WARN, CheckResult, num

COP_PER_K_MID = sum(t2.COP_PER_K) / 2  # 2,5 % je Kelvin Vorlauf
DISINFECTION_C = 60.0


class YearBasis:
    """Jahreswerte für die Wirkung, aus dem Kontext; jede Größe None, wenn sie sich nicht rechnen lässt."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    @cached_property
    def year(self) -> dict | None:
        dd = self.ctx.master.get("heating_degree_days")
        rows = self.ctx.daily_rows_window
        if not dd or len(rows) < k1.PROJECTION_MIN_DAYS:
            return None
        return k1.project_year(rows, self.ctx.outdoor_daily, self.ctx.tz, float(dd))

    @cached_property
    def electricity_kwh(self) -> float | None:
        return self.year["electricity_kwh"] if self.year else None

    @cached_property
    def dhw_electricity_kwh(self) -> float | None:
        """Warmwasserstrom im Jahr: Strom der Ladungen je Tag × 365."""
        charges = [c for c in self.ctx.dhw_charges if c.electricity_kwh is not None]
        span = (self.ctx.end - self.ctx.dhw_section_start) / 86400
        if not charges or span < 1:
            return None
        return sum(c.electricity_kwh for c in charges) / span * 365

    @cached_property
    def heating_electricity_kwh(self) -> float | None:
        if self.electricity_kwh is None:
            return None
        return max(0.0, self.electricity_kwh - (self.dhw_electricity_kwh or 0.0))

    @cached_property
    def cop(self) -> float | None:
        y = self.year
        return y["heat_kwh"] / y["electricity_kwh"] if y and y["electricity_kwh"] else None

    @cached_property
    def dhw_cop(self) -> float:
        eff = w1.efficiency_of(self.ctx.dhw_charges)
        return eff[1] if eff else w1.FIELD_DHW_COP

    @cached_property
    def price(self) -> float | None:
        """Mittlerer Strompreis €/kWh: aus den Tageskosten (auch dynamisch), sonst der Arbeitspreis."""
        rows = self.ctx.daily_rows_window
        costs = [self.ctx.day_costs.get(r["day"]) for r in rows]
        kwh = sum(r["electricity_kwh"] for r in rows)
        if rows and all(c is not None for c in costs) and kwh > 0:
            return sum(costs) / kwh
        price = self.ctx.master.get("tariff_price")
        return float(price) if price else None


def _share(kwh: float | None, share: float, note: str) -> tuple[float, str] | None:
    return None if kwh is None or share <= 0 else (kwh * share, note)


def _t1(r: CheckResult, y: YearBasis):
    excess = (r.value or 0) - t2.LOSS_OK_K
    return _share(y.heating_electricity_kwh, excess * COP_PER_K_MID,
                  f"{num(excess, '.1f')} K weniger Vorlauf × 2,5 % des Heizstroms")


def _t6(r: CheckResult, y: YearBasis):
    return _share(y.heating_electricity_kwh, COP_PER_K_MID, "1 K weniger Vorlauf × 2,5 % des Heizstroms")


def _w2(r: CheckResult, y: YearBasis):
    temp = r.value or 0
    if temp > w1.EFFICIENCY_MAX_C:
        return _share(y.dhw_electricity_kwh, (temp - w1.EFFICIENCY_MAX_C) * w1.DHW_PENALTY_PCT_PER_K / 100,
                      f"{num(temp - w1.EFFICIENCY_MAX_C, '.0f')} K kühler × 1,4 % des Warmwasserstroms")
    volume = y.ctx.master.get("dhw_tank_volume_l")
    interval = r.details.get("interval_days") or w1.DISINFECTION_INTERVAL_DAYS
    if not volume or temp >= DISINFECTION_C:
        return None
    heat = float(volume) * RHO_CP_KJ_PER_L_K * (DISINFECTION_C - temp) / 3600
    per_year = 365 / interval
    # Aufheizen auf 60 °C übernimmt meist der Heizstab: 1 kWh Strom je kWh Wärme (obere Grenze)
    return -heat * per_year, (f"{num(per_year, '.0f')} Aufheizungen × {num(heat, '.1f')} kWh mit dem Heizstab, "
                              "mit der Wärmepumpe etwa die Hälfte")


def _w3(r: CheckResult, y: YearBasis):
    found, heater = r.details.get("count") or 0, r.details.get("heater_kwh")
    per_week = r.value or 0
    if not found or not heater or per_week <= 1:
        return None
    return (per_week - 1) * 52 * heater / found, "Aufheizungen über eine pro Woche × Heizstab-Strom je Aufheizung"


def _w4(r: CheckResult, y: YearBasis):
    d = r.details
    loss, tank = d.get("loss_w"), d.get("tank_mean")
    if loss is None or tank is None or not d.get("limit_w"):
        return None
    allowed = d["limit_w"] * (tank - w1.ERP_AMBIENT_C) / w1.ERP_DELTA_K  # Grenze Klasse C bei heutiger Temperatur
    excess = loss - allowed
    if excess <= 0:
        return None
    return excess * 8.76 / y.dhw_cop, f"{num(excess, '.0f')} W über Klasse C, mit der Arbeitszahl beim Warmwasser"


def _w5(r: CheckResult, y: YearBasis):
    return _share(y.dhw_electricity_kwh, (r.value or 0) / 100, "Einbuße × Warmwasserstrom; nur wenn ein Ladefenster "
                                                                "zu den Duschzeiten passt")


def _c5(r: CheckResult, y: YearBasis):
    if y.electricity_kwh is None or y.cop is None:
        return None
    excess = ((r.value or 0) - 2.0) / 100
    return _share(y.electricity_kwh, excess * (1 - 1 / y.cop),
                  "Heizstab-Strom über 2 %, den die Wärmepumpe mit ihrer Arbeitszahl liefern würde")


def _k4(r: CheckResult, y: YearBasis):
    paid, mean = r.details.get("paid_ct"), r.details.get("mean_ct")
    if y.electricity_kwh is None or paid is None or mean is None:
        return None
    return None, (y.electricity_kwh * (paid - mean) / 100, "Jahresstrom × Unterschied zum mittleren Preis")


def _k3(r: CheckResult, y: YearBasis):
    return None, (-(r.value or 0), "aus K3")


# Prüfung → Wirkung in kWh Strom im Jahr (positiv = Ersparnis) mit Rechenweg. Rückgabe (kWh, Rechenweg) oder
# (None, (€, Rechenweg)), wenn sich nur Euro rechnen lassen.
_IMPACT: dict[str, Callable] = {"T1": _t1, "T6": _t6, "W2": _w2, "W3": _w3, "W4": _w4, "W5": _w5, "C5": _c5,
                                "K3": _k3, "K4": _k4}

# Zielkonflikte: Prüfung → Sätze, die bei ihrer Aktion stehen.
CONFLICTS: dict[str, tuple[str, ...]] = {
    "W2": ("Mehr Hygiene kostet Strom: Jede Aufheizung braucht Energie (oft den Heizstab), ein wärmerer Speicher "
           "verliert mehr (W4) und senkt die Effizienz (W1).",),
    "W5": ("Der Speicher muss bis zum nächsten Duschen reichen (W6).",
           "Bei dynamischem Strompreis kann die günstigste Stunde eine andere sein als die wärmste (K4)."),
    "K4": ("Die günstigste Stunde ist nicht immer die wärmste; Laden bei kalter Luft kostet Effizienz (W5).",),
    "T6": ("Nur so weit senken, wie alle Räume warm bleiben; werden einzelne Räume zu kühl, fehlt der hydraulische "
           "Abgleich.",),
    "T1": ("Weniger Pumpenleistung kann einzelne Räume kühler machen; am besten zusammen mit dem Abgleich.",),
    "W3": ("Seltener aufheizen spart Heizstab-Strom; liegt der Speicher unter 50 °C, muss es aber regelmäßig "
           "bleiben (W2).",),
}


def annotate(results: list[CheckResult], y: YearBasis) -> None:
    """Ergänzt die Aktionen gelber und roter Prüfungen um `impact` und `conflicts` (nach attach_actions)."""
    for r in results:
        if r.action is None or r.verdict not in (HINT, WARN):
            continue
        if r.check_id in CONFLICTS:
            r.action["conflicts"] = list(CONFLICTS[r.check_id])
        rule = _IMPACT.get(r.check_id)
        out = rule(r, y) if rule else None
        if out is None:
            continue
        kwh, how = out
        if kwh is None:
            eur, how = how
        else:
            eur = kwh * y.price if y.price is not None else None
        r.action["impact"] = {"kwh_year": None if kwh is None else round(kwh),
                              "eur_year": None if eur is None else round(eur), "basis": how}
