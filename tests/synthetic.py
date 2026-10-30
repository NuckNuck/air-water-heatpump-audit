"""Synthetische Anlage für Vergleichstests: zehn Tage mit allen Rollen, Takten, Abtauen, Warmwasser und einem Ereignis.

Deterministisch (keine Zufallszahlen), damit der Bericht vor und nach einem Umbau Zahl für Zahl gleich sein muss.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

H, M = 3600, 60
START = datetime(2026, 1, 5, tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
END = START + 10 * 24 * H
EVENT = START + 6 * 24 * H + 9 * H
MASTER = {"hydraulic_separation": "parallel_buffer", "flow_rate_min_lpm": 14.3, "circuit_flow_max_lpm": 60.0,
          "room_temp_target": 21.0, "heating_hours": 6000,
          "capacity_min_table": {35: {-7: 3.9, 2: 3.5, 7: 3.5}, 45: {-7: 3.7, 2: 3.2, 7: 3.2}},
          "dhw_tank_volume_l": 200, "tariff_price": 0.25, "tariff_base_fee": 60.0, "household_price": 0.30,
          "reference_fuel_price": 0.12, "reference_efficiency": 0.9, "heating_degree_days": 3500}
HEATER_KW = {"immersion_heater": 3.0, "booster_heater": 0.0, "booster_heater_2": 0.0}


def _outdoor(t: float) -> float:
    return 2.0 + 4.0 * math.sin(2 * math.pi * (t - START) / (24 * H) - math.pi / 2)


def series() -> dict:
    s: dict[str, list] = {k: [] for k in (
        "electricity_meter", "compressor_running", "compressor_frequency", "flow_temp", "return_temp", "flow_rate",
        "outdoor_temp", "outdoor_temp_reference", "pump_running", "defrost", "dhw_active", "immersion_heater",
        "booster_heater", "booster_heater_2", "heartbeat", "controller_heating_consumed", "controller_dhw_consumed",
        "controller_date", "flow_setpoint", "circuit_flow_temp", "circuit_return_temp", "circuit_pump_running",
        "room_temp", "dhw_tank_temp", "dhw_setpoint")}
    meter = 1000.0
    tank = 45.0
    uptime = 0.0
    day_kwh = 0.0
    t = START
    step = M
    while t < END:
        minute = int((t - START) // M)
        hour_of_day = (minute // 60) % 24
        in_cycle = minute % 60
        # Vor dem Ereignis 40 min an / 20 min aus, danach 50 / 10 (weniger Takten)
        on_len = 40 if t < EVENT else 50
        dhw = hour_of_day == 5 and in_cycle < 45
        on = in_cycle < on_len or dhw
        defrost = on and not dhw and in_cycle in (20, 21) and minute % 180 < 60
        outdoor = _outdoor(t)
        setpoint = 35.0 - 0.5 * outdoor
        if on:
            flow = (48.0 if dhw else setpoint + 2.5) - (6.0 if defrost else 0.0)
            ret = flow - (5.0 if not defrost else -2.0)
            freq = 30.0 + 2 * abs(outdoor)
            kw = 1.3 if not dhw else 1.8
        else:
            flow = setpoint - 1.0
            ret = flow - 0.5
            freq = 0.0
            kw = 0.02
        # Speicher: lädt um 5 Uhr auf 46 °C (am Tag 8 Desinfektion auf 60 °C), kühlt 0,2 K/h ab, Zapfen um 18 Uhr
        if dhw:
            target = 60.0 if minute // 1440 == 8 else 46.0
            tank = min(target, tank + (1.0 if target > 50 else 0.5))
        else:
            tank -= 0.2 / 60
        if hour_of_day == 18 and in_cycle < 10:
            tank -= 1.0
        # Neustart der Schnittstelle am Tag 3 um 12:00, Lücke am Tag 4 von 10:00 bis 10:20
        if minute == 3 * 24 * 60 + 12 * 60:
            uptime = 0.0
        gap = 4 * 24 * 60 + 10 * 60 <= minute < 4 * 24 * 60 + 10 * 60 + 20
        uptime += step
        meter += kw / 60
        day_kwh += kw / 60
        if not gap:
            s["heartbeat"].append((t, uptime))
            s["electricity_meter"].append((t, round(meter, 1)))
            s["compressor_running"].append((t, 1.0 if on else 0.0))
            s["compressor_frequency"].append((t, round(freq)))
            s["flow_temp"].append((t, round(flow * 2) / 2))
            s["return_temp"].append((t, round(ret * 2) / 2))
            s["flow_rate"].append((t, 16.0 if on or in_cycle < on_len + 10 else 0.0))
            s["pump_running"].append((t, 1.0 if on or in_cycle < on_len + 10 else 0.0))
            s["outdoor_temp"].append((t, round(outdoor + 0.8, 1)))
            s["defrost"].append((t, 1.0 if defrost else 0.0))
            s["dhw_active"].append((t, 1.0 if dhw else 0.0))
            s["immersion_heater"].append((t, 1.0 if dhw and in_cycle < 5 and minute // (24 * 60) == 2 else 0.0))
            s["booster_heater"].append((t, 0.0))
            s["booster_heater_2"].append((t, 0.0))
            s["flow_setpoint"].append((t, round(setpoint, 1)))
            s["circuit_flow_temp"].append((t, round((flow - 2.0 if on and not dhw else setpoint - 1.5) * 2) / 2))
            s["circuit_return_temp"].append((t, round((setpoint - 4.0) * 2) / 2))
            s["circuit_pump_running"].append((t, 1.0))
            s["dhw_tank_temp"].append((t, round(tank * 2) / 2))
            s["dhw_setpoint"].append((t, 46.0))
            s["room_temp"].append((t, round(22.3 + 0.3 * math.sin(2 * math.pi * minute / 1440), 1)))
        if minute % 60 == 0:
            s["outdoor_temp_reference"].append((t, round(outdoor, 1)))
        if minute % 1440 == 2:  # Steuerung meldet um ihre Mitternacht (2 min spät) den Vortag
            s["controller_heating_consumed"].append((t, round(day_kwh * 0.9, 1)))
            s["controller_dhw_consumed"].append((t, round(day_kwh * 0.15, 1)))
            s["controller_date"].append((t, f"day{minute // 1440}"))
            day_kwh = 0.0
        t += step
    return s


EVENTS = [{"time": EVENT, "kind": "pump_setting", "note": "Pumpe eine Stufe tiefer"}]
