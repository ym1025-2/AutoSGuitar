"""同時発音のまとめ上げ。

和音はキースイッチ 1 個が全体を支配するため（docs/02-sound-source-spec.md §2.7 ⑤)、
発音開始が近いノートを 1 つの Event にまとめる。
"""

from __future__ import annotations

from ..model import Event, Note


def group_events(notes: list[Note], tolerance: int) -> list[Event]:
    """発音開始が `tolerance` tick 以内のノートを 1 イベントにまとめる。

    ラフな打ち込みでは和音の構成音が完全には揃っていないため、許容幅を持たせる。
    """
    if not notes:
        return []

    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    events: list[Event] = []
    current: list[Note] = [ordered[0]]
    anchor = ordered[0].start

    for note in ordered[1:]:
        if note.start - anchor <= tolerance:
            current.append(note)
        else:
            events.append(Event(start=anchor, notes=current))
            current = [note]
            anchor = note.start
    events.append(Event(start=anchor, notes=current))

    for i, event in enumerate(events):
        event.index = i
    return events
