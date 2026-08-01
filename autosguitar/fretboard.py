"""フレットボードモデル。docs/04-articulation-rules.md §4.8

Phase 1 では**音域による近似判定の述語のみ**を提供する。
Phase 2 で弦割り当て（動的計画法による運指最適化）を実装したら、
各述語の実装だけを差し替えれば全ルールが本来の条件に移行する。

この音源の発音域は 7 弦 22 フレットのギターそのもの:

    最低音 B1 (35) = 7 弦開放
    最高音 D6 (86) = 1 弦 E4(64) + 22 フレット   ← sfz の hikey=d6 と一致
"""

from __future__ import annotations

from .profile.ksop import MAX_FRET, OPEN_STRINGS

#: 低音弦（7 弦 B1 / 6 弦 E2 / 5 弦 A2）で押さえられる音高の目安。
#: パームミュートが成立する音域の近似に使う。
LOW_STRING_CEILING = 57

#: チョーキングが現実的に成立する音高の下限の近似。
#: Phase 2 では「高音弦かつフレット 5 以上」に置換する。
BEND_FLOOR = 55


def string_candidates(pitch: int) -> list[int]:
    """その音高を押さえられる弦の index（0 = 最低音弦）を返す。"""
    return [
        i
        for i, open_pitch in enumerate(OPEN_STRINGS)
        if 0 <= pitch - open_pitch <= MAX_FRET
    ]


def on_low_string(pitch: int, ceiling: int = LOW_STRING_CEILING) -> bool:
    """低音弦で鳴らされうるか（パームミュート判定の近似）。

    Phase 2 では弦割り当ての結果を直接見る。
    """
    return pitch <= ceiling


def bendable(pitch: int, floor: int = BEND_FLOOR) -> bool:
    """チョーキングが現実的な音域か。

    Phase 2 では「高音弦かつフレット 5 以上」に置換する。
    """
    return pitch >= floor


def reachable_on_one_string(a: int, b: int, max_interval: int) -> bool:
    """2 音が同一弦上で（＝スライドせずに）つながりうるか。

    Phase 1 は音程差による近似。Phase 2 では実際の弦割り当てを比較する。
    """
    return abs(b - a) <= max_interval


def is_playable_chord(pitches: list[int], max_span: int = 5) -> tuple[bool, str]:
    """和音が物理的に押さえられるかを判定する（Phase 2 の先行実装）。

    各音を異なる弦に割り当てられ、かつ押弦するフレットの幅が `max_span` 以内なら
    演奏可能とみなす。開放弦（フレット 0）は幅の計算から除外する。
    """
    if len(pitches) > len(OPEN_STRINGS):
        return False, f"同時発音数 {len(pitches)} が弦数 {len(OPEN_STRINGS)} を超えています"

    ordered = sorted(pitches)
    assignment: list[int] = []

    def search(idx: int, next_string: int) -> bool:
        if idx == len(ordered):
            fretted = [f for f in assignment if f > 0]
            return not fretted or (max(fretted) - min(fretted)) <= max_span
        for s in range(next_string, len(OPEN_STRINGS)):
            fret = ordered[idx] - OPEN_STRINGS[s]
            if 0 <= fret <= MAX_FRET:
                assignment.append(fret)
                if search(idx + 1, s + 1):
                    return True
                assignment.pop()
        return False

    if not search(0, 0):
        return False, "この和音を押さえられる運指が見つかりません"
    return True, ""
