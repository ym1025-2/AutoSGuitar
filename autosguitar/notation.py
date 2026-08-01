"""ノート名の表示。docs/02-sound-source-spec.md §2.1

内部処理はすべて MIDI ノート番号で行い、ノート名は表示専用とする。
マニュアル / KSMap / sfz は C-1=0（中央ド = C4）、Studio One は
C-2=0（中央ド = C3、127 = G8）で 1 オクターブずれるため。
"""

from __future__ import annotations

_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

#: 表記系 → オクターブ番号のオフセット
SYSTEMS = {
    "s1": -2,  # Studio One / ヤマハ式。127 = G8
    "manual": -1,  # マニュアル / KSMap / sfz。中央ド = C4
}

DEFAULT_SYSTEM = "s1"


def note_name(pitch: int, system: str = DEFAULT_SYSTEM) -> str:
    """MIDI ノート番号をノート名にする。"""
    try:
        offset = SYSTEMS[system]
    except KeyError:
        known = ", ".join(sorted(SYSTEMS))
        raise KeyError(f"未知の表記系: {system!r}（利用可能: {known}）") from None
    return f"{_NAMES[pitch % 12]}{pitch // 12 + offset}"


def labelled(pitch: int, system: str = DEFAULT_SYSTEM) -> str:
    """ノート名と番号を併記する。ログ表示ではこちらを使う。"""
    return f"{note_name(pitch, system)}({pitch})"
