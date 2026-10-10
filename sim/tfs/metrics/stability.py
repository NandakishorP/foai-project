"""Market stability around an event (Topic 6 shock analysis; metrics fixed in DECISIONS D-053 before any run).

An *event* is a breaking-news shock, the later correction of its true/false status, or
the start of a collateral depeg. Every metric looks at the window that starts at the
event and lasts `WINDOW` ticks, or until the next event if that comes first, and
compares it with the same-length window just before.

- recovery: ticks until the price is within ε of p*_avail and stays there to the window's
  end. A run that never settles counts as the full window (restricted mean, as H3c).
- max_deviation: the largest |price − p*_avail| in the window.
- overshoot: the largest excursion *beyond* p*_avail in the direction p*_avail moved at
  the event (0 if the price never passes it). Not defined for a depeg: no news, no direction.
- volume_ratio, active_ratio: main-market volume, and traders active per tick, in the window
  relative to the window before (liquidity withdrawal shows as a ratio below 1).
- revert_share: share of main-market trades in the window that reverted.
- trend_push: the trend followers' net exposure bought in the window, signed so that
  positive means "in the direction of the event" (amplification).
- arb_gap: mean |logit main − logit reference| in the window; arb_volume: the arbitrageur's
  main-market volume in it; gap_halflife: ticks until the gap first falls to half its
  peak after the peak (the window length if it never does).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from tfs.simulation import MarketRecord

WINDOW = 40


@dataclass(frozen=True)
class EventMetrics:
    recovery: float
    max_deviation: float
    overshoot: float
    volume_ratio: float
    active_ratio: float
    revert_share: float
    trend_push: float
    arb_gap: float
    arb_volume: float
    gap_halflife: float


def events(record: MarketRecord, depeg_start: int | None) -> dict[str, int]:
    """The market's events by name: the first shock, its correction, the depeg start (when present)."""
    out: dict[str, int] = {}
    if record.shock_ticks:
        out["shock"] = record.shock_ticks[0]
    if record.correction_ticks:
        out["correction"] = record.correction_ticks[0]
    if depeg_start is not None:
        out["depeg"] = depeg_start
    return out


def window_end(start: int, all_events: dict[str, int], ticks: int) -> int:
    later = [t for t in all_events.values() if t > start]
    return min([start + WINDOW, ticks, *later])


def direction(record: MarketRecord, tick: int) -> int:
    """+1 if p*_avail rose at the event, −1 if it fell (+1 if it did not move)."""
    move = record.p_avail[tick] - record.p_avail[tick - 1] if tick > 0 else 0.0
    return -1 if move < 0 else 1


def _sum(series: dict[str, np.ndarray], kind: str, a: int, b: int) -> float:
    return float(series[kind][a:b].sum()) if kind in series else 0.0


def _ratio(num: float, den: float) -> float:
    return num / den if den > 0 else math.nan


def event_metrics(record: MarketRecord, name: str, all_events: dict[str, int], epsilon: float) -> EventMetrics:
    t0 = all_events[name]
    t1 = window_end(t0, all_events, len(record.price_main))
    before = max(0, t0 - (t1 - t0))
    price, avail = record.price_main[t0:t1], record.p_avail[t0:t1]
    gap = np.abs(price - avail)

    within = gap < epsilon
    if not within[-1]:
        recovery = float(t1 - t0)
    else:
        outside = np.flatnonzero(~within)
        recovery = 0.0 if outside.size == 0 else float(outside[-1] + 1)

    d = direction(record, t0)
    overshoot = math.nan if name == "depeg" else float(max(0.0, np.max(d * (price - avail))))

    total_volume = sum(record.volume_main.values())
    active = record.active_main
    reverts = float(record.reverts_main[t0:t1].sum())
    trades = float(record.trades_main[t0:t1].sum())

    venue_gap = np.abs(np.log(record.price_main / (1 - record.price_main))
                       - np.log(record.price_ref / (1 - record.price_ref)))[t0:t1]
    peak = int(np.argmax(venue_gap))
    after_peak = np.flatnonzero(venue_gap[peak:] <= venue_gap[peak] / 2)
    halflife = float(peak + after_peak[0]) if after_peak.size and venue_gap[peak] > 0 else float(t1 - t0)

    return EventMetrics(
        recovery=recovery,
        max_deviation=float(gap.max()),
        overshoot=overshoot,
        volume_ratio=_ratio(float(total_volume[t0:t1].sum()), float(total_volume[before:t0].sum())),
        active_ratio=_ratio(float(active[t0:t1].mean()), float(active[before:t0].mean())),
        revert_share=_ratio(reverts, reverts + trades),
        trend_push=d * _sum(record.flow_main, "trend", t0, t1),
        arb_gap=float(venue_gap.mean()),
        arb_volume=_sum(record.volume_main, "arbitrageur", t0, t1),
        gap_halflife=halflife,
    )
