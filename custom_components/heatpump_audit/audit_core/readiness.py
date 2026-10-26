"""Datenreife: ab wann jedes Audit genug Daten für seine Urteile hat.

Die Termine sind Hochrechnungen, keine Messung: Volle Tage zählen ab der nächsten Mitternacht, gezählte Vorkommnisse
(Zyklen, Pausen, Heizstunden) mit der bisherigen Rate weiter. Fällt ein Tag durch (Lücken, zu wenig Strom), rückt
der Termin nach hinten.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import days
from .result import ELAPSED, FULL_DAYS, RATE, CheckResult


def _midnight_after(t: float, n: int, tz: str) -> float:
    """Die n-te lokale Mitternacht nach t (n = 1: die nächste)."""
    zone = ZoneInfo(tz)
    d = datetime.fromtimestamp(t, zone).date() + timedelta(days=n)
    return datetime(d.year, d.month, d.day, tzinfo=zone).timestamp()


def _first_full_day_end(since: float, tz: str) -> float:
    """Ende des ersten vollen Tages ab since: beginnt since nicht um Mitternacht, zählt erst der Folgetag."""
    first = days.midnights(since, since + 2 * 86400, tz)[0]
    return _midnight_after(first, 1, tz)


def check_eta(p: dict, now: float, tz: str = days.DEFAULT_TZ) -> tuple[bool, float | None]:
    """(erreicht, Zeitpunkt). Erreicht: ungefähr wann; offen: voraussichtlich wann, None = nicht absehbar."""
    have, need, since, lag = p["have"], p["need"], p["since"], p.get("lag_h", 0) * 3600
    reached = have >= need
    if p["basis"] == ELAPSED:
        return reached, since + need * 3600
    if p["basis"] == FULL_DAYS:
        if reached:  # frühestmöglicher Zeitpunkt, falls alle Tage zählten
            first_end = _first_full_day_end(since, tz)
            return True, min(now, _midnight_after(first_end, int(need) - 1, tz) + lag)
        # Der laufende Tag zählt mit, wenn der Zeitraum vor seiner Mitternacht begann.
        today_counts = since <= days.midnights(now - 2 * 86400, now, tz)[-1]
        remaining = int(need - have) + (0 if today_counts else 1)
        return False, _midnight_after(now, remaining, tz) + lag
    if p["basis"] == RATE:
        elapsed = now - since
        if reached:
            return True, since + elapsed * need / have if have else now
        if have <= 0 or elapsed <= 0:
            return False, None
        return False, now + (need - have) * elapsed / have
    raise ValueError(p["basis"])


def audit_readiness(start: float, results: list[CheckResult], now: float, tz: str = days.DEFAULT_TZ) -> dict:
    """Datenreife eines Audits: der späteste Termin seiner Prüfungen mit Mindest-Datenmenge.

    Prüfungen ohne `progress` (keine Mindestmenge, oder es fehlt ein Eingang) zählen nicht.
    """
    checks = []
    for r in results:
        if not r.progress:
            continue
        reached, eta = check_eta(r.progress, now, tz)
        checks.append({"check_id": r.check_id, "have": r.progress["have"], "need": r.progress["need"],
                       "unit": r.progress["unit"], "reached": reached, "eta": eta})
    pending = [c for c in checks if not c["reached"]]
    if not checks:
        return {"start": start, "reached": True, "eta": None, "checks": []}
    if pending:
        etas = [c["eta"] for c in pending]
        eta = None if None in etas else max(etas)
    else:
        eta = max(c["eta"] for c in checks)
    return {"start": start, "reached": not pending, "eta": eta, "checks": checks}
