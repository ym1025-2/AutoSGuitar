"""イベント間の関係を表す特徴量を埋める。

音高・音価そのものから導ける特徴は Event の property 側に置いてある
（docs/05-architecture.md §5.2）。ここで埋めるのは前後のイベントを
参照しないと決まらないものだけ。
"""

from __future__ import annotations

from ..model import Event


def fill_relations(events: list[Event]) -> list[Event]:
    """ioi / gap / gap_before を埋める。

    - ioi        : 次イベント開始 − 自分の開始
    - gap        : 次イベント開始 − 自分の終了（負なら重なっている）
    - gap_before : 自分の開始 − 直前イベントの終了
    """
    for i, event in enumerate(events):
        if i + 1 < len(events):
            nxt = events[i + 1]
            event.ioi = nxt.start - event.start
            event.gap = nxt.start - event.end
        else:
            event.ioi = None
            event.gap = None

        if i > 0:
            event.gap_before = event.start - events[i - 1].end
        else:
            event.gap_before = None
    return events


def interval_to_next(events: list[Event], index: int) -> int | None:
    """単声どうしの隣接イベントの音程差（符号つき半音）。

    どちらかが和音の場合は None を返す。
    """
    if index + 1 >= len(events):
        return None
    a, b = events[index], events[index + 1]
    if not (a.is_monophonic and b.is_monophonic):
        return None
    return b.lowest - a.lowest
