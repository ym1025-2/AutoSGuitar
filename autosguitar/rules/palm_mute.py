"""パームミュート判定。docs/04-articulation-rules.md §4.2

単一条件では決まらないため複合スコアで判定する。最も効くのはペダルトーン検出。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..model import Event

#: context 注釈によるスコア補正。リードとクリーンではパームミュートを事実上禁止する
CONTEXT_BIAS = {
    "lead": -1.0,
    "clean": -1.0,
    "backing_chord": -0.1,
    "backing_riff": 0.1,
}


@dataclass
class PalmMuteScore:
    total: float
    reasons: list[str] = field(default_factory=list)

    @property
    def primary_reason(self) -> str:
        return self.reasons[0] if self.reasons else "score"


def detect_pedal_tones(
    events: list[Event],
    window_bars: int,
    min_count: int,
    min_share: float,
) -> set[int]:
    """ペダルトーンとして鳴らされているイベントの index 集合を返す。

    窓（既定 2 小節）の中で、最低音でありかつ 3 回以上・全発音の 40% 以上を
    占める音高をペダル音とみなす。メタル / ロックのリフで最頻出の形であり、
    メーカー製デモの trk3（B1 をペダルにする構造）とも一致する。
    """
    if not events:
        return set()

    by_bar: dict[int, list[int]] = defaultdict(list)
    for i, event in enumerate(events):
        bar = event.grid.bar if event.grid else 0
        by_bar[bar].append(i)

    pedal: set[int] = set()
    bars = sorted(by_bar)
    for start_pos in range(len(bars)):
        window = bars[start_pos : start_pos + window_bars]
        if len(window) < window_bars and start_pos != 0:
            break
        indices = [i for bar in window for i in by_bar[bar]]
        if len(indices) < min_count:
            continue

        lowest = min(events[i].lowest for i in indices)
        matching = [i for i in indices if events[i].lowest == lowest]
        if len(matching) < min_count:
            continue
        if len(matching) / len(indices) < min_share:
            continue

        # 和音の中にたまたまペダル音が含まれるだけの場合を除く
        pedal.update(i for i in matching if events[i].polyphony <= 2)

    return pedal


def score(
    event: Event,
    previous: Event | None,
    is_pedal: bool,
    context: str | None,
    cfg: dict,
) -> PalmMuteScore:
    """パームミュートらしさのスコアを返す。閾値以上ならパームミュートと判定する。"""
    weights = cfg.get("weights", {})
    total = 0.0
    reasons: list[str] = []

    def add(key: str, default: float, reason: str) -> None:
        nonlocal total
        value = float(weights.get(key, default))
        if value:
            total += value
            if value > 0:
                reasons.append(reason)

    if event.highest >= cfg.get("pitch_reject_above", 62):
        add("high_pitch", -1.0, "high_pitch")
    elif event.lowest <= cfg.get("pitch_strong_below", 57):
        add("low_pitch", 0.40, "low_pitch")

    if event.duration_ratio <= cfg.get("duration_ratio_max", 0.5):
        add("staccato", 0.20, "staccato")

    if is_pedal:
        add("pedal_tone", 0.60, "pedal_tone")

    if event.is_power_chord:
        add("power_chord", 0.20, "power_chord")

    if event.is_full_chord:
        add("full_chord", -0.60, "full_chord")

    if previous is not None and previous.is_monophonic and event.is_monophonic:
        if previous.lowest == event.lowest:
            add("repeated_pitch", 0.10, "repeated_pitch")

    bias = CONTEXT_BIAS.get(context or "", 0.0)
    total += bias

    # ペダルトーン検出が効いた場合はそれを主因として報告する
    reasons.sort(key=lambda r: r != "pedal_tone")
    return PalmMuteScore(total=total, reasons=reasons)


def is_palm_mute(
    event: Event,
    previous: Event | None,
    is_pedal: bool,
    context: str | None,
    cfg: dict,
) -> tuple[bool, PalmMuteScore]:
    result = score(event, previous, is_pedal, context, cfg)
    return result.total >= cfg.get("score_threshold", 0.5), result
