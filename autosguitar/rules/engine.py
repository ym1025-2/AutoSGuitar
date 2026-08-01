"""ルールエンジン。注釈と自動ルールを優先度順に適用して Decision を作る。

優先度は docs/03-annotation-layer.md §3.4 のチェーンに従う。
自動ルールの適用順は docs/04-articulation-rules.md §4.9 のとおり
デッドノート → レガート → パームミュート → サステイン。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..annotation import Resolved
from ..midiio.reader import BarMap, TempoMap
from ..model import Articulation, Decision, Event, Stroke
from . import dead_note, legato, palm_mute, stroke as stroke_rules


@dataclass
class EngineContext:
    bar_map: BarMap
    tempo_map: TempoMap
    profile: object
    settings: object


def _articulation_from_manual_ks(profile, pitch: int) -> tuple[Articulation | None, Stroke | None]:
    return profile.KS_TO_ARTICULATION.get(pitch, (None, None))


def decide(
    events: list[Event],
    resolved: list[Resolved],
    ctx: EngineContext,
) -> list[Decision]:
    """全イベントの判定を行う。"""
    settings = ctx.settings
    profile = ctx.profile

    contexts = [r.context for r in resolved]

    pedal = palm_mute.detect_pedal_tones(
        events,
        window_bars=int(settings.palm_mute.get("pedal_window_bars", 2)),
        min_count=int(settings.palm_mute.get("pedal_min_count", 3)),
        min_share=float(settings.palm_mute.get("pedal_min_share", 0.40)),
    )

    articulations: list[Articulation | None] = [None] * len(events)
    sources: list[str] = [""] * len(events)
    suppressed: list[bool] = [False] * len(events)
    manual_strokes: list[Stroke | None] = [None] * len(events)

    # ── 奏法の決定（逐次。レガート判定が直前の結果を参照するため）
    for i, event in enumerate(events):
        r = resolved[i]
        previous = events[i - 1] if i > 0 else None
        previous_articulation = articulations[i - 1] if i > 0 else None

        if r.lock:
            articulations[i] = None
            sources[i] = r.lock_source or "annotation:lock"
            suppressed[i] = True
            continue

        if r.manual_ks is not None:
            art, stroke = _articulation_from_manual_ks(profile, r.manual_ks)
            articulations[i] = art
            manual_strokes[i] = stroke
            sources[i] = f"manual_ks:{r.manual_ks}"
            # ユーザーが置いた KS は入力トラックにそのまま残るので二重に出さない
            suppressed[i] = True
            continue

        if r.force is not None:
            articulations[i] = r.force
            sources[i] = r.force_source
            continue

        if dead_note.is_dead_note(event, settings.dead_note):
            articulations[i] = dead_note.articulation_for(event)
            sources[i] = "rule:dead_note"
            continue

        if legato.is_legato(event, previous, previous_articulation, settings.legato):
            articulations[i] = Articulation.HAMMER_PULL
            sources[i] = "rule:legato"
            continue

        is_pm, pm_score = palm_mute.is_palm_mute(
            event, previous, i in pedal, contexts[i], settings.palm_mute
        )
        if is_pm:
            articulations[i] = Articulation.PALM_MUTE
            sources[i] = f"rule:palm_mute({pm_score.primary_reason})"
        else:
            articulations[i] = Articulation.SUSTAIN
            sources[i] = "default:sustain"

    # ── ストロークの決定
    # polish 0（雛形）ではダウン / アップを打ち分けず、手編集しやすい最小限の
    # 出力にする（docs/01-overview.md §1.6）
    if settings.polish >= 1:
        strokes = stroke_rules.assign(
            events,
            articulations,
            contexts,
            ctx.bar_map,
            ctx.tempo_map,
            profile.STROKED_ARTICULATIONS,
            settings.stroke,
        )
    else:
        strokes = [stroke_rules.StrokeAssignment(None) for _ in events]

    # ── Decision の組み立て
    decisions: list[Decision] = []
    first_emitted = True
    for i, event in enumerate(events):
        r = resolved[i]
        articulation = articulations[i]
        assignment = strokes[i]

        final_stroke = assignment.stroke
        stroke_source = assignment.source

        if manual_strokes[i] is not None:
            final_stroke = manual_strokes[i]
            stroke_source = sources[i]
        if r.stroke is not None and articulation in profile.STROKED_ARTICULATIONS:
            final_stroke = r.stroke
            stroke_source = r.stroke_source

        decision = Decision(
            event=event,
            articulation=articulation or Articulation.SUSTAIN,
            stroke=final_stroke,
            source=sources[i] or "default",
            stroke_source=stroke_source,
            suppressed=suppressed[i],
        )

        if not decision.suppressed:
            if first_emitted:
                decision.ccs.update(settings.cc_defaults)
                first_emitted = False
            if settings.polish >= 1:
                _attach_slide_cc(decision, events, i, profile)

        decisions.append(decision)

    return decisions


def _attach_slide_cc(decision: Decision, events: list[Event], index: int, profile) -> None:
    """スライド系の奏法に距離 CC を付ける。

    CC26 = スライドアップ / ダウン、CC27 = スライドイン
    （docs/02-sound-source-spec.md §2.6）。距離は直前の音との音程差から求める。
    スライドインは開始音が譜面上に存在しないため、距離を推定できる場合のみ付ける。
    """
    if decision.articulation not in (Articulation.SLIDE_UP, Articulation.SLIDE_DOWN):
        return
    if index == 0:
        return
    previous = events[index - 1]
    event = events[index]
    if not (previous.is_monophonic and event.is_monophonic):
        return
    interval = abs(event.lowest - previous.lowest)
    if interval == 0:
        return
    decision.ccs[profile.CC_INTERVAL_A] = profile.slide_interval_cc(interval)
