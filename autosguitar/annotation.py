"""注釈レイヤーの解決。

docs/03-annotation-layer.md §3.4 の優先度チェーンを実装する。

    1. ロック（注釈 127）
    2. 手動キースイッチ（入力に既に置かれた KS ノート）
    3. 奏法の強制（注釈 105–118）
    4. ストローク強制（注釈 125–126）
    5. context（注釈 120–123）
    6. 自動ルール
    7. 既定値
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Annotation, Articulation, Event, Note, Stroke


@dataclass
class Resolved:
    """1 イベントに解決された注釈と手動指定。"""

    lock: bool = False
    lock_source: str = ""
    manual_ks: int | None = None
    force: Articulation | None = None
    force_source: str = ""
    stroke: Stroke | None = None
    stroke_source: str = ""
    context: str | None = None
    context_source: str = ""


@dataclass
class AnnotationResult:
    per_event: list[Resolved]
    warnings: list[str] = field(default_factory=list)


def _pick(candidates: list[Annotation]) -> tuple[Annotation | None, bool]:
    """競合する注釈から 1 つ選ぶ。

    より短い注釈を優先する（区間指定の中の 1 音だけを上書きできるようにするため）。
    長さが同じ場合は開始 tick が遅いほうを採り、競合ありとして報告する。
    """
    if not candidates:
        return None, False
    ordered = sorted(candidates, key=lambda a: (a.length, -a.start))
    best = ordered[0]
    conflict = len(ordered) > 1 and ordered[1].length == best.length
    return best, conflict


def _bind_manual_keyswitches(
    events: list[Event],
    keyswitches: list[Note],
    tolerance: int,
    max_lead: int,
) -> tuple[dict[int, int], list[str]]:
    """入力に置かれた KS ノートを、それが修飾するイベントに結びつける。

    メーカー製 MIDI では KS は実音と同一 tick か、わずかに手前に置かれる
    （docs/02-sound-source-spec.md §2.7）。同一 tick から `max_lead` tick 手前までを
    探索範囲とする。
    """
    bindings: dict[int, int] = {}
    warnings: list[str] = []
    starts = [e.start for e in events]

    for ks in sorted(keyswitches, key=lambda n: n.start):
        target: int | None = None
        for i, start in enumerate(starts):
            if start >= ks.start - tolerance:
                if start - ks.start <= max_lead:
                    target = i
                break
        if target is None:
            warnings.append(
                f"tick {ks.start} の手動キースイッチ（ノート {ks.pitch}）に対応する実音が"
                "見つかりません。無視します"
            )
            continue
        bindings[target] = ks.pitch

    return bindings, warnings


def resolve(
    events: list[Event],
    annotations: list[Annotation],
    keyswitches: list[Note],
    *,
    chord_tolerance: int,
    ks_max_lead: int,
) -> AnnotationResult:
    """各イベントに対して注釈と手動 KS を解決する。"""
    resolved = [Resolved() for _ in events]
    warnings: list[str] = []

    bindings, ks_warnings = _bind_manual_keyswitches(
        events, keyswitches, chord_tolerance, ks_max_lead
    )
    warnings.extend(ks_warnings)

    for i, event in enumerate(events):
        covering = [a for a in annotations if a.covers(event.start)]

        locks = [a for a in covering if a.spec.get("lock")]
        if locks:
            resolved[i].lock = True
            resolved[i].lock_source = f"annotation:{locks[0].pitch}"

        if i in bindings:
            resolved[i].manual_ks = bindings[i]

        forces = [a for a in covering if "force" in a.spec]
        best, conflict = _pick(forces)
        if best is not None:
            name = best.spec["force"]
            try:
                resolved[i].force = Articulation(name)
            except ValueError:
                warnings.append(
                    f"注釈ノート {best.pitch} の force 値 {name!r} は未知の奏法です。無視します"
                )
            else:
                resolved[i].force_source = f"annotation:{best.pitch}"
            if conflict:
                warnings.append(
                    f"tick {event.start} で長さの等しい force 注釈が競合しています"
                    f"（ノート {best.pitch} を採用）"
                )

        strokes = [a for a in covering if "stroke" in a.spec]
        best, conflict = _pick(strokes)
        if best is not None:
            name = best.spec["stroke"]
            try:
                resolved[i].stroke = Stroke(name)
            except ValueError:
                warnings.append(
                    f"注釈ノート {best.pitch} の stroke 値 {name!r} は未知です。無視します"
                )
            else:
                resolved[i].stroke_source = f"annotation:{best.pitch}"
            if conflict:
                warnings.append(
                    f"tick {event.start} で長さの等しい stroke 注釈が競合しています"
                    f"（ノート {best.pitch} を採用）"
                )

        contexts = [a for a in covering if "context" in a.spec]
        best, conflict = _pick(contexts)
        if best is not None:
            resolved[i].context = best.spec["context"]
            resolved[i].context_source = f"annotation:{best.pitch}"
            if conflict:
                warnings.append(
                    f"tick {event.start} で長さの等しい context 注釈が競合しています"
                    f"（ノート {best.pitch} を採用）"
                )

    return AnnotationResult(per_event=resolved, warnings=warnings)
