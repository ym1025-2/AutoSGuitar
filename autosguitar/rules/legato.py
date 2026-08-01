"""ハンマリング / プリング判定。docs/04-articulation-rules.md §4.4

音源側に自動検出があるため、ツールは「ここはレガートである」という判定だけを行い、
キースイッチ 30 を置く。
"""

from __future__ import annotations

from ..model import Articulation, Event

#: 音程差の上限は「同一弦で届く範囲」の近似。
#: Phase 2 でフレットボードモデルが入ったら same_string() に置換する（§4.8）。
from ..fretboard import reachable_on_one_string


def is_legato(
    event: Event,
    previous: Event | None,
    previous_articulation: Articulation | None,
    cfg: dict,
) -> bool:
    """レガート（ハンマリング / プリング）かどうかを判定する。"""
    if previous is None or event.gap_before is None:
        return False  # 曲頭。必ずピッキングされる

    if not (event.is_monophonic and previous.is_monophonic):
        return False

    # 重なっている（gap_before < 0）か、間隔が十分に小さい
    if event.gap_before > cfg.get("max_gap", 0):
        return False

    interval = event.lowest - previous.lowest
    if interval == 0:
        return False
    if not reachable_on_one_string(previous.lowest, event.lowest, cfg.get("max_interval", 5)):
        return False

    # パームミュート中はレガートしない
    if previous_articulation is Articulation.PALM_MUTE:
        return False

    return True
