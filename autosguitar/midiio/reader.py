"""MIDI の読み込みと分解。

入力トラックを「実音 / 既存キースイッチ / 注釈ノート / その他」に分離し、
テンポマップと小節マップを構築する。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import mido

from ..model import Annotation, Note

DEFAULT_TEMPO = 500_000  # mido の既定（120 BPM）


@dataclass
class TempoMap:
    """(tick, microseconds per beat) の並び。先頭は必ず tick 0。"""

    entries: list[tuple[int, int]] = field(default_factory=lambda: [(0, DEFAULT_TEMPO)])

    def tempo_at(self, tick: int) -> int:
        current = self.entries[0][1]
        for at, tempo in self.entries:
            if at > tick:
                break
            current = tempo
        return current

    def bpm_at(self, tick: int) -> float:
        return 60_000_000.0 / self.tempo_at(tick)


@dataclass
class BarMap:
    """拍子変化を考慮して tick と小節位置を相互変換する。

    entries は (開始 tick, 開始小節番号, 1 小節の tick 数, 1 拍の tick 数)。
    """

    entries: list[tuple[int, int, int, int]]

    def locate(self, tick: int) -> tuple[int, int, int]:
        """tick → (小節番号, 小節内 tick, 1 拍の tick 数) を返す。"""
        start, bar0, ticks_per_bar, ticks_per_beat = self.entries[0]
        for entry in self.entries:
            if entry[0] > tick:
                break
            start, bar0, ticks_per_bar, ticks_per_beat = entry
        delta = tick - start
        bar = bar0 + delta // ticks_per_bar
        return bar, delta % ticks_per_bar, ticks_per_beat


@dataclass
class TrackContent:
    """1 トラックを役割ごとに分解した結果。"""

    index: int
    name: str
    playable: list[Note] = field(default_factory=list)
    keyswitches: list[Note] = field(default_factory=list)
    annotations_raw: list[Note] = field(default_factory=list)
    out_of_range: list[Note] = field(default_factory=list)


@dataclass
class SourceMidi:
    path: Path
    midi: mido.MidiFile
    tpq: int
    tempo_map: TempoMap
    bar_map: BarMap
    tracks: list[TrackContent]
    target_index: int

    @property
    def target(self) -> TrackContent:
        return self.tracks[self.target_index]


def _absolute(track: mido.MidiTrack):
    """(絶対 tick, message) を順に返す。"""
    tick = 0
    for msg in track:
        tick += msg.time
        yield tick, msg


def _extract_notes(track: mido.MidiTrack) -> list[Note]:
    """note_on / note_off を対応付けて Note のリストにする。

    velocity 0 の note_on は note_off として扱う。閉じられなかったノートは
    トラック終端で閉じる。
    """
    pending: dict[int, list[tuple[int, int]]] = defaultdict(list)
    notes: list[Note] = []
    last_tick = 0

    for tick, msg in _absolute(track):
        last_tick = max(last_tick, tick)
        if msg.type == "note_on" and msg.velocity > 0:
            pending[msg.note].append((tick, msg.velocity))
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            queue = pending.get(msg.note)
            if queue:
                start, velocity = queue.pop(0)
                # 長さ 0 のノートは 1 tick に伸ばす（後段の除算を安全にするため）
                notes.append(Note(start, max(tick, start + 1), msg.note, velocity))

    for pitch, queue in pending.items():
        for start, velocity in queue:
            notes.append(Note(start, max(last_tick, start + 1), pitch, velocity))

    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes


def _track_name(track: mido.MidiTrack) -> str:
    for msg in track:
        if msg.type == "track_name":
            # メーカー製 MIDI には NUL や壊れたバイトが混ざることがある
            return msg.name.split("\x00")[0].strip()
    return ""


def _build_tempo_map(midi: mido.MidiFile) -> TempoMap:
    entries: list[tuple[int, int]] = []
    for track in midi.tracks:
        for tick, msg in _absolute(track):
            if msg.type == "set_tempo":
                entries.append((tick, msg.tempo))
    if not entries:
        return TempoMap()
    entries.sort(key=lambda e: e[0])
    # 同一 tick に複数ある場合は最後を採用
    deduped: list[tuple[int, int]] = []
    for tick, tempo in entries:
        if deduped and deduped[-1][0] == tick:
            deduped[-1] = (tick, tempo)
        else:
            deduped.append((tick, tempo))
    if deduped[0][0] != 0:
        deduped.insert(0, (0, DEFAULT_TEMPO))
    return TempoMap(deduped)


def _build_bar_map(midi: mido.MidiFile, tpq: int) -> BarMap:
    changes: list[tuple[int, int, int]] = []  # (tick, numerator, denominator)
    for track in midi.tracks:
        for tick, msg in _absolute(track):
            if msg.type == "time_signature":
                changes.append((tick, msg.numerator, msg.denominator))
    changes.sort(key=lambda c: c[0])

    deduped: list[tuple[int, int, int]] = []
    for change in changes:
        if deduped and deduped[-1][0] == change[0]:
            deduped[-1] = change
        else:
            deduped.append(change)
    if not deduped or deduped[0][0] != 0:
        deduped.insert(0, (0, 4, 4))

    entries: list[tuple[int, int, int, int]] = []
    bar = 0
    for i, (tick, num, den) in enumerate(deduped):
        ticks_per_beat = int(tpq * 4 / den)
        ticks_per_bar = max(1, ticks_per_beat * num)
        entries.append((tick, bar, ticks_per_bar, ticks_per_beat))
        if i + 1 < len(deduped):
            span = deduped[i + 1][0] - tick
            bar += max(0, span // ticks_per_bar)
    return BarMap(entries)


def _classify(notes: list[Note], profile, annotation_block: tuple[int, int]) -> TrackContent:
    content = TrackContent(index=-1, name="")
    low, high = annotation_block
    for note in notes:
        if profile.is_playable(note.pitch):
            content.playable.append(note)
        elif low <= note.pitch <= high:
            content.annotations_raw.append(note)
        elif profile.is_keyswitch(note.pitch):
            content.keyswitches.append(note)
        else:
            content.out_of_range.append(note)
    return content


def read(
    path: str | Path,
    profile,
    annotation_block: tuple[int, int] = (105, 127),
    track_index: int | None = None,
    ks_track_name: str = "AutoSG_KS",
) -> SourceMidi:
    """MIDI ファイルを読み、処理対象トラックを決めて分解する。

    `track_index` が None の場合は、発音域の音を最も多く含むトラックを選ぶ。
    ツール自身が生成した KS トラックは候補から除外する。
    """
    path = Path(path)
    midi = mido.MidiFile(str(path))
    tpq = midi.ticks_per_beat

    tracks: list[TrackContent] = []
    for i, track in enumerate(midi.tracks):
        content = _classify(_extract_notes(track), profile, annotation_block)
        content.index = i
        content.name = _track_name(track)
        tracks.append(content)

    if track_index is not None:
        if not 0 <= track_index < len(tracks):
            raise IndexError(
                f"トラック番号 {track_index} は範囲外です（0–{len(tracks) - 1}）"
            )
        target = track_index
    else:
        candidates = [t for t in tracks if t.name != ks_track_name]
        if not candidates:
            raise ValueError("処理対象になるトラックがありません")
        best = max(candidates, key=lambda t: len(t.playable))
        if not best.playable:
            raise ValueError(
                f"発音域（{profile.PLAYABLE_LOW}–{profile.PLAYABLE_HIGH}）の音を含む"
                "トラックが見つかりません"
            )
        target = best.index

    return SourceMidi(
        path=path,
        midi=midi,
        tpq=tpq,
        tempo_map=_build_tempo_map(midi),
        bar_map=_build_bar_map(midi, tpq),
        tracks=tracks,
        target_index=target,
    )


def build_annotations(notes: list[Note], settings) -> tuple[list[Annotation], list[Note]]:
    """注釈ノートを Annotation に変換する。

    設定に定義のないノート番号は「未知の注釈」として第 2 要素で返す。
    """
    annotations: list[Annotation] = []
    unknown: list[Note] = []
    for note in notes:
        spec = settings.annotation_spec(note.pitch)
        if spec is None:
            unknown.append(note)
            continue
        annotations.append(Annotation(note.start, max(note.end, note.start + 1), note.pitch, spec))
    annotations.sort(key=lambda a: (a.start, a.length))
    return annotations, unknown
