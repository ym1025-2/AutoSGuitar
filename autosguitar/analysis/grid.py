"""拍位置と支配的な分割の推定。

docs/04-articulation-rules.md §4.1 の「小節ごとに発音位置ヒストグラムから
支配的な分割を推定し、スロット番号の偶奇でダウン/アップを決める」を実装する。
"""

from __future__ import annotations

from collections import defaultdict

from ..midiio.reader import BarMap
from ..model import Event, GridPos


def _snap_error(offsets: list[int], division: int) -> float:
    """各発音位置から最寄りのグリッド線までの距離の平均。"""
    if not offsets:
        return 0.0
    total = 0
    for offset in offsets:
        remainder = offset % division
        total += min(remainder, division - remainder)
    return total / len(offsets)


def estimate_division(
    offsets: list[int],
    ticks_per_beat: int,
    candidates: list[int],
    tolerance: int,
) -> int:
    """小節内の発音位置から 1 スロットあたりの tick 数を推定する。

    候補（1 拍を何分割するか）を粗いほうから試し、平均スナップ誤差が
    許容内に収まる最初のものを採用する。どれも収まらなければ最も細かいものを使う。
    """
    ordered = sorted(set(candidates))
    if not ordered:
        ordered = [4]

    best_division = max(1, ticks_per_beat // ordered[-1])
    for n in ordered:
        division = max(1, ticks_per_beat // n)
        if _snap_error(offsets, division) <= tolerance:
            return division
    return best_division


def assign_grid(
    events: list[Event],
    bar_map: BarMap,
    candidates: list[int],
    tolerance: int,
) -> list[Event]:
    """各イベントに GridPos を与える。分割は小節単位で推定する。"""
    located: list[tuple[Event, int, int, int]] = []
    per_bar: dict[int, list[int]] = defaultdict(list)

    for event in events:
        bar, tick_in_bar, ticks_per_beat = bar_map.locate(event.start)
        located.append((event, bar, tick_in_bar, ticks_per_beat))
        per_bar[bar].append(tick_in_bar)

    divisions: dict[int, int] = {}
    for bar, offsets in per_bar.items():
        ticks_per_beat = next(tpb for _, b, _, tpb in located if b == bar)
        divisions[bar] = estimate_division(offsets, ticks_per_beat, candidates, tolerance)

    for event, bar, tick_in_bar, ticks_per_beat in located:
        division = divisions[bar]
        slot = round(tick_in_bar / division)
        distance_to_beat = tick_in_bar % ticks_per_beat
        is_strong = min(distance_to_beat, ticks_per_beat - distance_to_beat) <= tolerance
        event.grid = GridPos(
            bar=bar,
            tick_in_bar=tick_in_bar,
            division=division,
            slot=slot,
            is_strong=is_strong,
        )
    return events
