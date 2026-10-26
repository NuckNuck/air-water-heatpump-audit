"""Zeitreihen und Intervalle.

Eine Zeitreihe ist eine nach Zeit sortierte Liste von Punkten (t, v): t in Unix-Sekunden, v gilt bis zum nächsten
Punkt (Zustands-Semantik wie in Home Assistant). Ein Intervall ist ein Paar (a, b) mit a < b.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Callable, Iterable

Point = tuple[float, object]
Series = list[Point]
Interval = tuple[float, float]


def dedupe(series: Series) -> Series:
    """Entfernt Punkte, die den vorherigen Wert nur wiederholen."""
    out: Series = []
    for t, v in series:
        if not out or out[-1][1] != v:
            out.append((t, v))
    return out


def value_at(series: Series, t: float):
    """Der zum Zeitpunkt t gültige Wert, None vor dem ersten Punkt."""
    i = bisect_right(series, t, key=lambda p: p[0])
    return series[i - 1][1] if i else None


def clip(series: Series, start: float, end: float) -> Series:
    """Schneidet auf [start, end) zu; der vor start gültige Wert wird auf start gesetzt."""
    i = bisect_right(series, start, key=lambda p: p[0])
    j = bisect_left(series, end, key=lambda p: p[0])
    head = [(start, series[i - 1][1])] if i else []
    return head + list(series[i:max(i, j)])


def intervals_where(series: Series, pred: Callable[[object], bool], start: float, end: float) -> list[Interval]:
    """Intervalle in [start, end), in denen pred(Wert) gilt."""
    pts = clip(series, start, end)
    out: list[Interval] = []
    for i, (t, v) in enumerate(pts):
        t_next = pts[i + 1][0] if i + 1 < len(pts) else end
        if t_next > t and pred(v):
            if out and out[-1][1] == t:
                out[-1] = (out[-1][0], t_next)
            else:
                out.append((t, t_next))
    return out


def total(intervals: Iterable[Interval]) -> float:
    return sum(b - a for a, b in intervals)


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    """Sortiert und verschmilzt überlappende oder angrenzende Intervalle."""
    out: list[Interval] = []
    for a, b in sorted(i for i in intervals if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def intersect(xs: list[Interval], ys: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a1, b1 in normalize(xs):
        for a2, b2 in normalize(ys):
            a, b = max(a1, a2), min(b1, b2)
            if b > a:
                out.append((a, b))
    return normalize(out)


def subtract(xs: list[Interval], ys: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    ys = normalize(ys)
    for a, b in normalize(xs):
        cur = a
        for c, d in ys:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
        if cur < b:
            out.append((cur, b))
    return out


def overlaps(interval: Interval, others: Iterable[Interval]) -> bool:
    a, b = interval
    return any(c < b and d > a for c, d in others)


def combine(xs: Series, ys: Series, fn: Callable[[object, object], object], start: float, end: float) -> Series:
    """Verknüpft zwei Zustands-Zeitreihen punktweise zu einer neuen (z. B. Vorlauf − Rücklauf)."""
    xs, ys = clip(xs, start, end), clip(ys, start, end)
    times = sorted({t for t, _ in xs} | {t for t, _ in ys})
    out: Series = []
    ix = iy = -1
    for t in times:
        while ix + 1 < len(xs) and xs[ix + 1][0] <= t:
            ix += 1
        while iy + 1 < len(ys) and ys[iy + 1][0] <= t:
            iy += 1
        if ix >= 0 and iy >= 0:
            out.append((t, fn(xs[ix][1], ys[iy][1])))
    return out


def weighted_values(series: Series, intervals: list[Interval]) -> list[tuple[object, float]]:
    """Werte mit der Dauer, die sie innerhalb der Intervalle gelten."""
    out: list[tuple[object, float]] = []
    for a, b in normalize(intervals):
        pts = clip(series, a, b)
        for i, (t, v) in enumerate(pts):
            t_next = pts[i + 1][0] if i + 1 < len(pts) else b
            if t_next > t:
                out.append((v, t_next - t))
    return out


def weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    half = sum(w for _, w in pairs) / 2
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return None
