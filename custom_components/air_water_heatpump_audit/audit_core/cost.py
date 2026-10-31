"""Audit 5 – Kosten (Spezifikation: docs/specification.md, Abschnitt 7).

Was kostet eine Kilowattstunde Wärme, was kostet das Heizen im Jahr, und lohnt sich der Tarif? Strom immer vom Zähler
(Grundsatz 1), Wärme aus den gültigen Tagen von Audit 1. Preise sind Stammdaten; ein dynamischer Tarif kommt als Rolle
`price_signal` (€/kWh) dazu. Herstellerneutral: nur Rollen und Stammdaten.
"""

from __future__ import annotations

from bisect import bisect_right

from . import days
from .efficiency import HEATING_LIMIT_C, ROOM_BASE_C, WEEK_DAYS
from .heat import time_mean
from .result import (DERIVED, ELAPSED, FULL_DAYS, HINT, INFO, NOT_ASSESSABLE, OK, SOURCED, CheckResult, count, num,
                     progress)
from .series import Interval, Series, clip, intervals_where, total, value_at

PROJECTION_MIN_DAYS = 14  # K2: zwei Wochen, damit kalte und milde Tage dabei sind
PROJECTION_MIN_SPREAD_K = 4.0  # K2: Spannweite der Tages-Gradtage für die Ausgleichsgerade
REFERENCE_TOLERANCE = 1.10  # K1: Wärme ist auf etwa ±10 % genau; erst darüber ist die WP sicher teurer
PRICE_TIMING_TOLERANCE = 1.03  # K4: gezahlter Mittelpreis bis 3 % über dem Zeitmittel ist Zufall der Woche
# K5: Sperren und Dimmen. Seit 2024 (§ 14a EnWG, BNetzA BK6-22-300) gibt es keine feste Höchstdauer mehr, nur eine
# Mindestleistung von 4,2 kW; bewertet wird deshalb nur, ob danach der Heizstab nachheizt (teuer, derived).
AFTER_LOCK_S = 2 * 3600
# K2: Effizienzklassen des Energieausweises nach Endenergie in kWh/(m²·a), GEG Anlage 10; bei einer Wärmepumpe ist
# die Endenergie der Strom. Der Ausweis bezieht sich auf die Gebäudenutzfläche, im Ein- und Zweifamilienhaus
# pauschal 1,2 × Wohnfläche (GEG § 82 Abs. 2; mit beheiztem Keller 1,35).
ENERGY_CLASSES = (("A+", 30), ("A", 50), ("B", 75), ("C", 100), ("D", 130), ("E", 160), ("F", 200), ("G", 250))
USEFUL_AREA_FACTOR = 1.2


def energy_class(kwh_per_m2: float) -> str:
    return next((label for label, limit in ENERGY_CLASSES if kwh_per_m2 < limit), "H")


def _on(v) -> bool:
    return v in (1, 1.0, True, "on")


def ct(eur: float) -> str:
    return num(100 * eur, ".1f")


def energy_cost(meter: Series, price: Series, a: float, b: float) -> float | None:
    """Kosten in € zwischen a und b: jeder Zählerschritt × der Preis, der zu Beginn des Schritts galt."""
    points = clip(meter, a, b)
    end_value = value_at(meter, b)
    if not points or end_value is None:
        return None
    points = points + [(b, end_value)]
    times = [t for t, _ in price]
    cost = 0.0
    for (t0, v0), (_, v1) in zip(points, points[1:]):
        i = bisect_right(times, t0)
        if not i:
            return None
        cost += (float(v1) - float(v0)) * float(price[i - 1][1])
    return cost


def day_cost(row: dict, meter: Series, price: Series, tariff_price: float | None, tz: str) -> float | None:
    """Kosten eines gültigen Tages: mit dynamischem Preis aus dem Zähler, sonst Strom × Arbeitspreis."""
    if price:
        a = days.parse(row["day"], tz)
        return energy_cost(meter, price, a, days.next_midnight(a, tz))
    return row["electricity_kwh"] * tariff_price if tariff_price is not None else None


def reference_heat_price(master: dict) -> float | None:
    """Was eine kWh Wärme mit dem Vergleichsbrennstoff kostet: Brennstoffpreis ÷ Jahresnutzungsgrad."""
    fuel, eff = master.get("reference_fuel_price"), master.get("reference_efficiency")
    return float(fuel) / float(eff) if fuel and eff else None


def _week(rows: list[dict]) -> list[dict] | None:
    return rows[-WEEK_DAYS:] if len(rows) >= WEEK_DAYS else None


def _missing_price(key: tuple[str, str]) -> CheckResult:
    return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Arbeitspreis des Stroms (oder Rolle "
                       "„dynamischer Strompreis“).", origin=DERIVED)


def check_heat_price(rows: list[dict], costs: dict[str, float | None], master: dict, since: float) -> CheckResult:
    """K1: Wärmepreis der Woche in ct/kWh, inklusive Grundpreis-Anteil, gegen den Vergleichsbrennstoff."""
    key = ("K1", "heat_price")
    prog = progress(len(rows), WEEK_DAYS, "days", FULL_DAYS, since)
    week = _week(rows)
    if week is None:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(rows), 'gültiger Tag', 'gültige Tage')}, "
                           f"nötig {WEEK_DAYS}.", origin=DERIVED, progress=prog)
    week_costs = [costs.get(r["day"]) for r in week]
    if any(c is None for c in week_costs):
        return _missing_price(key)
    heat = sum(r["heat_kwh"] for r in week)
    if heat <= 0:
        return CheckResult(*key, NOT_ASSESSABLE, text="Keine Wärme in der Woche.", origin=DERIVED, progress=prog)
    base = float(master.get("tariff_base_fee") or 0) * WEEK_DAYS / 365
    cost = sum(week_costs) + base
    price = cost / heat
    reference = reference_heat_price(master)
    text = (f"{days.display(week[0]['day'])} bis {days.display(week[-1]['day'])}: Wärme kostet {ct(price)} ct/kWh "
            f"({num(cost, '.2f')} € für {num(heat, '.0f')} kWh Wärme")
    text += ", mit Anteil am Grundpreis). " if base else "). "
    details = {"cost_eur": round(cost, 2), "heat_kwh": round(heat, 1), "base_fee_eur": round(base, 2),
               "reference_ct": None if reference is None else round(100 * reference, 1)}
    if reference is None:
        text += "Für einen Vergleich Preis und Nutzungsgrad des früheren Brennstoffs in den Stammdaten eintragen."
        return CheckResult(*key, INFO, round(100 * price, 1), "ct/kWh", text, DERIVED, details, progress=prog)
    text += f"Mit dem Vergleichsbrennstoff wären es {ct(reference)} ct/kWh. "
    if price <= reference * REFERENCE_TOLERANCE:
        verdict = OK
        text += ("Die Wärmepumpe ist günstiger." if price < reference else
                 "Etwa gleich teuer, im Rahmen der Messgenauigkeit der Wärme.")
    else:
        verdict = HINT
        text += ("In dieser Woche teurer als der Vergleich. Im Winter ist die Arbeitszahl niedriger; dauerhaft "
                 "teurer heißt: Tarif und Effizienz (Audit 1) prüfen.")
    return CheckResult(*key, verdict, round(100 * price, 1), "ct/kWh", text, DERIVED, details, progress=prog)


def degree_days(mean_c: float | None) -> float | None:
    """Gradtage eines Tages nach G20/15 (VDI 4710): 20 °C − Tagesmittel, nur unter der Heizgrenze 15 °C."""
    if mean_c is None:
        return None
    return ROOM_BASE_C - mean_c if mean_c < HEATING_LIMIT_C else 0.0


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ausgleichsgerade y = a + b·x (kleinste Quadrate)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def project_year(rows: list[dict], outdoor: Series, tz: str, year_degree_days: float) -> dict | None:
    """Jahreswerte aus Tageswerten: Strom und Wärme je Tag = Grundlast + Anteil je Gradtag (Ausgleichsgerade).

    Die Grundlast (Warmwasser, Bereitschaft) läuft 365 Tage, der Rest skaliert mit den Gradtagen des Standorts. Ist
    die Spannweite der Gradtage zu klein oder die Gerade unplausibel, wird alles mit den Gradtagen skaliert (grob)."""
    points = []
    for r in rows:
        a = days.parse(r["day"], tz)
        g = degree_days(time_mean(outdoor, [(a, days.next_midnight(a, tz))]))
        if g is not None:
            points.append((g, r))
    if len(points) < PROJECTION_MIN_DAYS:
        return None
    gs = [g for g, _ in points]
    out = {"days": len(points), "degree_days": round(sum(gs), 1)}
    for key in ("electricity_kwh", "heat_kwh"):
        ys = [r[key] for _, r in points]
        fitted = max(gs) - min(gs) >= PROJECTION_MIN_SPREAD_K
        if fitted:
            a, b = _fit(gs, ys)
            fitted = a >= 0 and b > 0
        out[key] = 365 * a + b * year_degree_days if fitted else sum(ys) * year_degree_days / max(sum(gs), 1e-9)
        out["method"] = "fit" if fitted else "ratio"
    return out


def check_annual_cost(rows: list[dict], outdoor: Series, costs: dict[str, float | None], master: dict, tz: str,
                      since: float, persons_mean: float | None = None) -> CheckResult:
    """K2: Hochrechnung aufs Jahr über die Gradtage des Standorts, mit Vergleich zum früheren Brennstoff. Mit
    Wohnfläche und Personen dazu Verbrauch je m² (mit Klasse des Energieausweises) und Kosten je Person."""
    key = ("K2", "annual_cost")
    prog = progress(len(rows), PROJECTION_MIN_DAYS, "days", FULL_DAYS, since)
    year_dd = master.get("heating_degree_days")
    if not year_dd:
        return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Gradtage des Standorts.", origin=SOURCED)
    if len(rows) < PROJECTION_MIN_DAYS:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"{count(len(rows), 'gültiger Tag', 'gültige Tage')}, nötig "
                           f"{PROJECTION_MIN_DAYS}.", origin=SOURCED, progress=prog)
    year = project_year(rows, outdoor, tz, float(year_dd))
    day_costs = [costs.get(r["day"]) for r in rows]
    if year is None:
        return CheckResult(*key, NOT_ASSESSABLE, text="Außentemperatur fehlt für die Gradtage.", origin=SOURCED,
                           progress=prog)
    if any(c is None for c in day_costs):
        return _missing_price(key)
    mean_price = sum(day_costs) / sum(r["electricity_kwh"] for r in rows)
    base = float(master.get("tariff_base_fee") or 0)
    cost = year["electricity_kwh"] * mean_price + base
    text = (f"Hochgerechnet ≈ {num(round(year['electricity_kwh'], -1), ',.0f')} kWh Strom und "
            f"≈ {num(round(cost, -1), ',.0f')} € im Jahr für ≈ {num(round(year['heat_kwh'], -2), ',.0f')} kWh Wärme "
            f"(aus {count(year['days'], 'Tag', 'Tagen')}, {num(year['degree_days'], '.0f')} von "
            f"{num(float(year_dd), ',.0f')} Gradtagen im Jahr")
    text += ")." if year["method"] == "fit" else "; grob, die Tage waren sich zu ähnlich)."
    details = year | {"cost_eur": round(cost), "mean_price_ct": round(100 * mean_price, 1)}
    reference = reference_heat_price(master)
    if reference is not None:
        ref_cost = year["heat_kwh"] * reference
        details["reference_cost_eur"] = round(ref_cost)
        text += (f" Mit dem früheren Brennstoff ≈ {num(round(ref_cost, -1), ',.0f')} €, "
                 f"{'Ersparnis' if ref_cost >= cost else 'Mehrkosten'} ≈ {num(round(abs(ref_cost - cost), -1), ',.0f')} €.")
    area = master.get("living_area_m2")
    if area:
        heat_m2, el_m2 = year["heat_kwh"] / float(area), year["electricity_kwh"] / float(area)
        label = energy_class(year["electricity_kwh"] / (USEFUL_AREA_FACTOR * float(area)))
        details |= {"heat_kwh_m2": round(heat_m2), "electricity_kwh_m2": round(el_m2), "energy_class": label}
        text += (f" Je m² Wohnfläche ≈ {num(heat_m2, '.0f')} kWh Wärme und ≈ {num(el_m2, '.0f')} kWh Strom im Jahr; "
                 f"im Energieausweis (Strom als Endenergie, Nutzfläche 1,2 × Wohnfläche) etwa Klasse {label}.")
    if persons_mean:
        details["cost_per_person_eur"] = round(cost / persons_mean)
        text += f" Je Person (Ø {num(persons_mean, '.1f')}) ≈ {num(round(cost / persons_mean, -1), ',.0f')} € im Jahr."
    for k in ("electricity_kwh", "heat_kwh"):
        details[k] = round(details[k])
    return CheckResult(*key, INFO, round(cost), "€/a", text, SOURCED, details, progress=prog)


def check_tariff(annual: CheckResult, master: dict, dynamic: bool) -> CheckResult:
    """K3: Lohnt der eigene Wärmepumpentarif gegen den Haushaltsstrom, Grundpreis des zweiten Zählers eingerechnet?"""
    key = ("K3", "tariff_benefit")
    household, tariff = master.get("household_price"), master.get("tariff_price")
    if dynamic:
        return CheckResult(*key, NOT_ASSESSABLE, text="Bei einem dynamischen Tarif bewertet K4 den Strompreis.",
                           origin=DERIVED)
    if not household or not tariff:
        return CheckResult(*key, NOT_ASSESSABLE, text="Stammdaten fehlen: Arbeitspreis von Wärmepumpen- und "
                           "Haushaltsstrom.", origin=DERIVED)
    kwh = annual.details.get("electricity_kwh") if annual.verdict == INFO else None
    if kwh is None:
        return CheckResult(*key, NOT_ASSESSABLE, text="Braucht die Hochrechnung aufs Jahr (K2).", origin=DERIVED,
                           progress=annual.progress)
    base = float(master.get("tariff_base_fee") or 0)
    benefit = (float(household) - float(tariff)) * kwh - base
    text = (f"{ct(float(tariff))} statt {ct(float(household))} ct/kWh bei ≈ {num(round(kwh, -1), ',.0f')} kWh im Jahr")
    text += f", abzüglich {num(base, '.0f')} € Grundpreis: " if base else ": "
    if benefit >= 0:
        verdict = OK
        text += f"Der Tarif spart ≈ {num(round(benefit, -1), ',.0f')} € im Jahr."
    else:
        verdict = HINT
        text += (f"Der Tarif kostet ≈ {num(round(-benefit, -1), ',.0f')} € im Jahr mehr als Haushaltsstrom. "
                 "Angebote vergleichen oder auf einen Zähler zusammenlegen.")
    return CheckResult(*key, verdict, round(benefit), "€/a", text, DERIVED, {"electricity_kwh": kwh,
                                                                              "base_fee_eur": base},
                       progress=annual.progress)


def check_price_timing(meter: Series, price: Series, since: float, end: float) -> CheckResult:
    """K4: Bei dynamischem Tarif: gezahlter Mittelpreis gegen das Zeitmittel des Preises."""
    key = ("K4", "price_timing")
    if not price:
        return CheckResult(*key, NOT_ASSESSABLE, text="Nur bei dynamischem Tarif (Rolle „dynamischer Strompreis“).",
                           origin=DERIVED)
    since = max(since, price[0][0])  # erst ab dem ersten aufgezeichneten Preis
    prog = progress((end - since) / 3600, WEEK_DAYS * 24, "hours", ELAPSED, since)
    if end - since < WEEK_DAYS * 86400:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"Bewertet ab {WEEK_DAYS} Tagen.", origin=DERIVED, progress=prog)
    cost = energy_cost(meter, price, since, end)
    m_a, m_b = value_at(meter, since), value_at(meter, end)
    mean = time_mean(price, [(since, end)])
    if cost is None or m_a is None or m_b is None or mean is None or float(m_b) <= float(m_a):
        return CheckResult(*key, NOT_ASSESSABLE, text="Preis oder Zählerstände fehlen.", origin=DERIVED,
                           progress=prog)
    paid = cost / (float(m_b) - float(m_a))
    text = f"Gezahlt im Mittel {ct(paid)} ct/kWh, der Preis lag im Mittel bei {ct(mean)} ct/kWh. "
    if paid <= mean * PRICE_TIMING_TOLERANCE:
        verdict = OK
        text += "Die Wärmepumpe läuft nicht bevorzugt in teuren Stunden."
    else:
        verdict = HINT
        text += ("Die Wärmepumpe läuft öfter in teuren Stunden. Warmwasser und, wo möglich, Heizen in günstige "
                 "Stunden legen (Zeitprogramm oder Preissteuerung).")
    return CheckResult(*key, verdict, round(100 * (paid / mean - 1), 1), "%", text, DERIVED,
                       {"paid_ct": round(100 * paid, 2), "mean_ct": round(100 * mean, 2)}, progress=prog)


def check_grid_lock(lock: Series, heaters: list[Interval], since: float, end: float) -> CheckResult:
    """K5: Sperren oder Dimmen durch den Netzbetreiber: wie oft, wie lange, und heizt danach der Heizstab nach?"""
    key = ("K5", "grid_lock")
    if not lock:
        return CheckResult(*key, NOT_ASSESSABLE, text="Eingang fehlt: Sperrsignal des Netzbetreibers.", origin=DERIVED)
    prog = progress((end - since) / 3600, WEEK_DAYS * 24, "hours", ELAPSED, since)
    if end - since < WEEK_DAYS * 86400:
        return CheckResult(*key, NOT_ASSESSABLE, text=f"Bewertet ab {WEEK_DAYS} Tagen.", origin=DERIVED,
                           progress=prog)
    locks = intervals_where(lock, _on, since, end)
    n_days = (end - since) / 86400
    longest = max((b - a for a, b in locks), default=0) / 3600
    windows = [(a, b + AFTER_LOCK_S) for a, b in locks]
    heater_h = sum(total([(max(a, x), min(b, y)) for a, b in heaters if a < y and b > x]) for x, y in windows) / 3600
    text = (f"{count(len(locks), 'Sperre', 'Sperren')} in {num(n_days, '.0f')} Tagen, zusammen "
            f"{num(total(locks) / 3600, '.1f')} h, längste {num(longest, '.1f')} h. ")
    if heater_h > 0:
        verdict = HINT
        text += (f"Der Heizstab lief während oder bis 2 h nach einer Sperre {num(heater_h, '.1f')} h – teurer "
                 "Ersatz für die Wärmepumpe.")
    else:
        verdict = OK
        text += "Der Heizstab springt dabei nicht ein." if locks else "Keine Sperre."
    return CheckResult(*key, verdict, round(len(locks) / n_days, 2), "1/d", text, DERIVED,
                       {"count": len(locks), "hours": round(total(locks) / 3600, 2), "longest_h": round(longest, 2),
                        "heater_after_h": round(heater_h, 2)}, progress=prog)


def daily_point(row: dict | None, cost: float | None, master: dict) -> dict:
    """Zeitstrahl: Wärmepreis des Tages (ohne Grundpreis) mit derselben Ampel wie K1."""
    if not row or cost is None or row["heat_kwh"] <= 0:
        return {"value": None, "verdict": NOT_ASSESSABLE}
    price = cost / row["heat_kwh"]
    reference = reference_heat_price(master)
    verdict = INFO if reference is None else OK if price <= reference * REFERENCE_TOLERANCE else HINT
    return {"value": round(100 * price, 1), "verdict": verdict, "cost_eur": round(cost, 2)}

