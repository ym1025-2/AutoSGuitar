"""ピッキング方向（ダウン / アップ）の決定。docs/04-articulation-rules.md §4.1

自動化の最大の価値がある部分。判定結果は Down / Up の明示キースイッチとして
出力する（オルタネイト KS はラウンドロビン非復帰のため使わない）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..midiio.reader import BarMap, TempoMap
from ..model import Articulation, Event, Stroke

#: ダウンピッキングを許可しない context
_NO_DOWNPICK_CONTEXTS = frozenset({"lead", "clean"})


@dataclass
class StrokeAssignment:
    stroke: Stroke | None
    source: str = ""


def _eighth_equivalent_bpm(bpm: float, ticks_per_beat: int, division: int) -> float:
    """その分割で弾いたときの「8 分音符換算 BPM」。

    8 分音符なら BPM そのまま、16 分音符なら 2 倍になる。
    ダウンピッキングの可否はこの値で判断する。
    """
    if division <= 0:
        return bpm
    notes_per_beat = ticks_per_beat / division
    return bpm * notes_per_beat / 2.0


def detect_gallops(events: list[Event], bar_map: BarMap) -> dict[int, Stroke]:
    """ギャロップ / 逆ギャロップを検出し、該当イベントのストロークを返す。

    - `8分 + 16分 + 16分`（ギャロップ）      → D, D, U
    - `16分 + 16分 + 8分`（逆ギャロップ）    → D, U, D
    """
    overrides: dict[int, Stroke] = {}

    for i in range(len(events) - 2):
        trio = events[i : i + 3]
        if trio[0].ioi is None or trio[1].ioi is None:
            continue

        _, tick_in_bar, ticks_per_beat = bar_map.locate(trio[0].start)
        # 拍頭から始まっていること
        if tick_in_bar % ticks_per_beat != 0:
            continue

        unit = ticks_per_beat / 4.0
        if unit <= 0:
            continue

        # 3 音目が最後のイベントなら、残りの拍をその音が占めるとみなす
        third_ioi = trio[2].ioi
        if third_ioi is None:
            third_ioi = ticks_per_beat - trio[0].ioi - trio[1].ioi

        # 3 音で 1 拍を埋めていること
        if trio[0].ioi + trio[1].ioi + third_ioi != ticks_per_beat:
            continue

        ratios = (
            round(trio[0].ioi / unit),
            round(trio[1].ioi / unit),
            round(third_ioi / unit),
        )
        if ratios == (2, 1, 1):
            overrides[trio[0].index] = Stroke.DOWN
            overrides[trio[1].index] = Stroke.DOWN
            overrides[trio[2].index] = Stroke.UP
        elif ratios == (1, 1, 2):
            overrides[trio[0].index] = Stroke.DOWN
            overrides[trio[1].index] = Stroke.UP
            overrides[trio[2].index] = Stroke.DOWN

    return overrides


def assign(
    events: list[Event],
    articulations: list[Articulation | None],
    contexts: list[str | None],
    bar_map: BarMap,
    tempo_map: TempoMap,
    stroked: frozenset,
    cfg: dict,
) -> list[StrokeAssignment]:
    """全イベントのストロークを決める。

    優先度（高→低）:
        1. 休符明けのリセット      … 1 拍以上の空白の後は必ずダウン
        2. ギャロップ検出
        3. ダウンピッキング上書き  … 低音域のパームミュートリフ
        4. 粗いグリッド            … 4 分音符以上の間隔なら全ダウン
        5. 基本のオルタネイト      … スロット番号の偶奇
    """
    rest_reset_beats = float(cfg.get("rest_reset_beats", 1.0))
    downpick_max_bpm = float(cfg.get("downpick_max_bpm", 170))
    downpick_max_pitch = int(cfg.get("downpick_max_pitch", 57))
    requires_context = bool(cfg.get("downpick_requires_context", False))

    gallops = detect_gallops(events, bar_map) if cfg.get("detect_gallop", True) else {}

    results: list[StrokeAssignment] = []
    parity_offset = 0
    current_bar: int | None = None

    for i, event in enumerate(events):
        articulation = articulations[i]
        if articulation is None or articulation not in stroked:
            results.append(StrokeAssignment(None))
            continue

        grid = event.grid
        _, _, ticks_per_beat = bar_map.locate(event.start)

        # 小節が変わったらグリッドに再アンカーする（小節頭は必ずダウンになる）
        if grid is not None and grid.bar != current_bar:
            current_bar = grid.bar
            parity_offset = 0

        slot = grid.slot if grid is not None else i
        division = grid.division if grid is not None else ticks_per_beat

        stroke = Stroke.DOWN if (slot + parity_offset) % 2 == 0 else Stroke.UP
        source = "rule:alternate"

        # ── 4. 粗いグリッド（4 分音符以上）は全ダウン
        if division >= ticks_per_beat:
            stroke, source = Stroke.DOWN, "rule:coarse_grid"

        # ── 3. ダウンピッキング上書き
        if articulation is Articulation.PALM_MUTE and event.lowest <= downpick_max_pitch:
            context = contexts[i]
            context_ok = (
                context == "backing_riff"
                if requires_context
                else context not in _NO_DOWNPICK_CONTEXTS
            )
            if context_ok:
                bpm = tempo_map.bpm_at(event.start)
                if _eighth_equivalent_bpm(bpm, ticks_per_beat, division) <= downpick_max_bpm:
                    stroke, source = Stroke.DOWN, "rule:downpick"

        # ── 2. ギャロップ
        if i in gallops:
            stroke, source = gallops[i], "rule:gallop"

        # ── 1. 休符明けのリセット（曲頭も含む）
        rest_ticks = rest_reset_beats * ticks_per_beat
        reanchored = False
        if event.gap_before is None or event.gap_before >= rest_ticks:
            stroke = Stroke.DOWN
            source = "rule:rest_reset" if event.gap_before is not None else "rule:phrase_start"
            reanchored = True

        # 位相の張り直しは休符明けのリセットでのみ行う。
        # ダウンピッキングやギャロップは局所的な上書きであり、これで位相を
        # 動かすと後続のオルタネイトが崩れる。
        if reanchored:
            desired = 0 if stroke is Stroke.DOWN else 1
            parity_offset = (desired - slot) % 2

        results.append(StrokeAssignment(stroke, source))

    return results
