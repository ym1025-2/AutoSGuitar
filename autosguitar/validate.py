"""出力の検証。docs/05-architecture.md §5.7"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .fretboard import is_playable_chord
from .model import Decision, Event, Note


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Issue:
    severity: Severity
    message: str
    tick: int | None = None

    def format(self) -> str:
        where = f"tick {self.tick}: " if self.tick is not None else ""
        return f"[{self.severity.value}] {where}{self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    def ok(self) -> bool:
        return not self.errors

    def warn(self, message: str, tick: int | None = None) -> None:
        self.issues.append(Issue(Severity.WARNING, message, tick))

    def error(self, message: str, tick: int | None = None) -> None:
        self.issues.append(Issue(Severity.ERROR, message, tick))


def validate(
    events: list[Event],
    decisions: list[Decision],
    rendered,
    out_of_range: list[Note],
    unknown_annotations: list[Note],
    profile,
) -> ValidationResult:
    result = ValidationResult()

    for note in out_of_range:
        result.warn(
            f"ノート {note.pitch} は発音域 "
            f"({profile.PLAYABLE_LOW}–{profile.PLAYABLE_HIGH}) の外にあり、"
            "この音源では発音しません",
            note.start,
        )

    for note in unknown_annotations:
        result.warn(
            f"注釈ブロックのノート {note.pitch} に対応する定義が rules.yaml に"
            "ありません。無視します",
            note.start,
        )

    for event in events:
        if event.polyphony > profile.MAX_POLYPHONY:
            result.warn(
                f"同時発音数 {event.polyphony} は弦数 {profile.MAX_POLYPHONY} を"
                "超えています",
                event.start,
            )
            continue
        if event.polyphony >= 3:
            playable, reason = is_playable_chord([n.pitch for n in event.notes])
            if not playable:
                result.warn(f"演奏困難な和音です: {reason}", event.start)

    for note in rendered.notes:
        if profile.is_playable(note.pitch):
            result.error(
                f"生成されたキースイッチ {note.pitch} が発音域に侵入しています"
                "（内部不整合）",
                note.start,
            )
        if not profile.is_keyswitch(note.pitch):
            result.error(
                f"生成されたノート {note.pitch} はキースイッチではありません（内部不整合）",
                note.start,
            )

    lead_missing = 0
    for note in rendered.notes:
        if note.is_release:
            continue
        if note.start > note.target_start:
            result.error(
                f"キースイッチ {note.pitch} が実音より後に配置されています（内部不整合）",
                note.start,
            )
        elif note.start == note.target_start:
            # 先行オフセットを取れなかった。分離トラックでは同一 tick の
            # イベント順序が保証されない（docs/02-sound-source-spec.md §2.8）
            lead_missing += 1

    if lead_missing:
        result.warn(
            f"曲頭に近いため先行オフセットを確保できなかったキースイッチが "
            f"{lead_missing} 件あります。分離トラックでは同一 tick のイベント順序が"
            "保証されないため、先頭の音が既定のキースイッチ（Sus_Down）で鳴る"
            "可能性があります。曲全体を少し後ろにずらすか --inline を使ってください",
            rendered.notes[0].start if rendered.notes else None,
        )

    return result
