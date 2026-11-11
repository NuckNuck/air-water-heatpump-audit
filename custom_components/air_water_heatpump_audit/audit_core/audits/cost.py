"""Audit 5 – Kosten: Was kostet die Wärme, was das Heizen im Jahr, und lohnt sich der Tarif?"""

from __future__ import annotations

from .. import cost as k1
from .. import heating_prices as hp
from .. import household as hh
from ..context import HEATER_ROLES, Context
from ..registry import SECTION, AuditSpec, CheckSpec, TimelineSpec
from ..result import HINT, OK
from ..series import intervals_where, normalize


def _point(ctx: Context, a: float, b: float, day: str) -> dict:
    row = ctx.timeline_row(day)
    point = k1.daily_point(row, ctx.day_costs.get(day), ctx.master, ctx.fixed_costs)
    if ctx.price_refs:
        # Wärmepreise anderer Heizsysteme an diesem Tag, auch ohne eigenen Wert (Sensor-ID → ct/kWh Wärme)
        heat = ctx.fixed_costs["annual_heat_kwh"]
        refs = {r["id"]: hp.day_heat_price(r, r["series"], a, b, ctx.master, heat) for r in ctx.price_refs}
        if refs := {k: v for k, v in refs.items() if v is not None}:
            point["references"] = refs
    return point


def _scale(master: dict) -> dict:
    """Wärmepreis in ct/kWh; Grenze = Vergleichsbrennstoff mit Messtoleranz wie K1. Ohne Vergleich keine Bänder."""
    reference = k1.reference_heat_price(master)
    limit = round(100 * reference * k1.REFERENCE_TOLERANCE, 1) if reference else None
    out = {"metric": "heat_price", "unit": "ct/kWh", "min": 0, "max": None, "decimals": 1,
           "bands": [[0, limit, OK], [limit, None, HINT]] if limit else []}
    if "price_references" in master:  # Vergleich eingeschaltet; leere Liste = kein Preis-Sensor gefunden
        out["references"] = master["price_references"]
    if reference:  # Wärmepreis der früheren Heizung als eigene Linie (Spezifikation 7.2)
        out["previous_heating"] = {"system": master.get("previous_heating_system"),
                                   "ct_per_kwh": round(100 * reference, 1)}
    if "fixed_costs" in master:  # was an festen Kosten im eigenen Wärmepreis steckt (Text unter dem Zeitstrahl)
        out["fixed_costs"] = master["fixed_costs"]
    return out


def _annual(ctx: Context):
    persons = hh.persons_mean(ctx.persons, hh.local_dates(ctx.section_start, ctx.end, ctx.tz)) if ctx.persons else None
    return k1.check_annual_cost(ctx.year_rows, ctx.outdoor_daily, ctx.day_costs, ctx.master, ctx.tz,
                                ctx.section_start, persons)


def _heaters(ctx: Context):
    return normalize([i for r in HEATER_ROLES for i in intervals_where(ctx.s[r], k1._on, ctx.section_start, ctx.end)])


AUDIT = AuditSpec(
    audit_id="cost", order=5, color="#546e7a", section=SECTION,
    roles=("electricity_meter", "price_signal", "grid_lock", *HEATER_ROLES,
           # Wärme und gültige Tage wie Audit 1
           "flow_temp", "return_temp", "flow_rate", "outdoor_temp", "outdoor_temp_reference", "dhw_active",
           "heartbeat", "controller_heat_today", "compressor_running", "pump_running", "defrost"),
    required_roles=("electricity_meter", "flow_temp", "return_temp", "flow_rate"),
    master_keys=("tariff_price", "tariff_price_unit", "heat_pump_meter", "tariff_base_fee", "tariff_base_fee_period", "meter_fee",
                 "meter_fee_period", "reduced_grid_fee", "household_price", "household_price_unit",
                 "reference_fuel_price", "reference_fuel_price_unit", "reference_efficiency", "previous_heating_system", "previous_consumption",
                 "previous_consumption_unit", "heating_degree_days", "living_area_m2", "household"),
    names={"de": "Kosten", "en": "Cost"},
    checks=(
        CheckSpec("K1", "heat_price", lambda ctx: k1.check_heat_price(ctx.daily_rows, ctx.day_costs, ctx.master,
                                                                       ctx.section_start, ctx.fixed_costs)),
        CheckSpec("K2", "annual_cost", _annual),
        CheckSpec("K3", "tariff_benefit", lambda ctx: k1.check_tariff(_annual(ctx), ctx.master,
                                                                       bool(ctx.s["price_signal"]))),
        CheckSpec("K4", "price_timing", lambda ctx: k1.check_price_timing(ctx.s["electricity_meter"],
                                                                           ctx.s["price_signal"], ctx.section_start,
                                                                           ctx.end), needs_role="price_signal"),
        CheckSpec("K5", "grid_lock", lambda ctx: k1.check_grid_lock(ctx.s["grid_lock"], _heaters(ctx),
                                                                     ctx.section_start, ctx.end)),
    ),
    timeline=TimelineSpec(scale=_scale, point=_point, metric_names={"de": "Wärmepreis", "en": "Heat price"},
                          statistics=True),
)
