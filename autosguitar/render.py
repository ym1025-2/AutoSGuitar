"""Decision からキースイッチノートと CC のイベント列を作る。

配置規則は docs/02-sound-source-spec.md §2.7 / §2.8。

- 全キースイッチを `ks_lead` tick 先行させる。分離トラック方式では同一 tick の
  イベント順序が保証されないため必須
- Slide_Out だけはリリース側（実音の終わり）に置く
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Decision


@dataclass(frozen=True)
class RenderedNote:
    """出力するキースイッチノート。"""

    start: int
    end: int
    pitch: int
    velocity: int
    #: このキースイッチが修飾する実音イベントの開始 tick（検証・レポート用）
    target_start: int = 0
    #: リリース側に配置するキースイッチか
    is_release: bool = False


@dataclass(frozen=True)
class RenderedCC:
    tick: int
    control: int
    value: int


@dataclass
class RenderResult:
    notes: list[RenderedNote]
    ccs: list[RenderedCC]

    def is_empty(self) -> bool:
        return not self.notes and not self.ccs


def render(decisions: list[Decision], profile, settings) -> RenderResult:
    notes: list[RenderedNote] = []
    ccs: list[RenderedCC] = []
    lead = settings.ks_lead
    velocity = settings.ks_velocity

    previous_ks: int | None = None

    for decision in decisions:
        if decision.suppressed:
            # 手動 KS / ロック区間。ラッチ状態が変わるので dedup の履歴も捨てる
            previous_ks = None
            continue

        event = decision.event
        is_release = decision.articulation in profile.RELEASE_ARTICULATIONS

        if is_release:
            # リリース側キースイッチは実音の終わりに置く
            ks_start = event.end
        else:
            ks_start = max(0, event.start - lead)

        for control, value in sorted(decision.ccs.items()):
            ccs.append(RenderedCC(tick=ks_start, control=control, value=int(value)))

        ks_pitch = profile.keyswitch_for(decision.articulation, decision.stroke)

        if settings.dedup and not is_release and ks_pitch == previous_ks:
            continue

        ks_end = max(ks_start + 1, event.start if not is_release else ks_start + max(1, lead))
        notes.append(
            RenderedNote(
                start=ks_start,
                end=ks_end,
                pitch=ks_pitch,
                velocity=velocity,
                target_start=event.start,
                is_release=is_release,
            )
        )

        if not is_release:
            previous_ks = ks_pitch

    notes.sort(key=lambda n: (n.start, n.pitch))
    ccs.sort(key=lambda c: (c.tick, c.control))
    return RenderResult(notes=notes, ccs=ccs)
