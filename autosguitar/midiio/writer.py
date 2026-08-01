"""MIDI の書き出し。docs/05-architecture.md §5.6

生成したキースイッチ / CC は専用トラック `AutoSG_KS` に分離する。
実行のたびにこのトラックをまるごと作り直すため、冪等性が構造的に保証される
（docs/03-annotation-layer.md §3.5）。

入力側のトラックは（ツール自身が過去に生成した KS トラックを除き）すべて保持する。
"""

from __future__ import annotations

from pathlib import Path

import mido

from ..render import RenderResult

#: 同一 tick でのイベント並び順。キースイッチは必ず実音より前に出す。
_PRIORITY_META = 0
_PRIORITY_CC = 1
_PRIORITY_NOTE_OFF = 2
_PRIORITY_KS_ON = 3
_PRIORITY_NOTE_ON = 4


def _absolute(track: mido.MidiTrack) -> list[tuple[int, mido.Message]]:
    tick = 0
    out = []
    for msg in track:
        tick += msg.time
        out.append((tick, msg))
    return out


def _priority(msg, keyswitch_pitches: frozenset[int]) -> int:
    if msg.is_meta:
        return _PRIORITY_META
    if msg.type == "control_change":
        return _PRIORITY_CC
    if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
        return _PRIORITY_NOTE_OFF
    if msg.type == "note_on":
        return _PRIORITY_KS_ON if msg.note in keyswitch_pitches else _PRIORITY_NOTE_ON
    return _PRIORITY_CC


def _to_track(
    entries: list[tuple[int, mido.Message]],
    keyswitch_pitches: frozenset[int] = frozenset(),
) -> mido.MidiTrack:
    """絶対 tick の列を delta time のトラックに変換する。"""
    ordered = sorted(
        enumerate(entries),
        key=lambda item: (item[1][0], _priority(item[1][1], keyswitch_pitches), item[0]),
    )
    track = mido.MidiTrack()
    previous = 0
    for _, (tick, msg) in ordered:
        track.append(msg.copy(time=tick - previous))
        previous = tick
    return track


def _dominant_channel(track: mido.MidiTrack, default: int = 0) -> int:
    counts: dict[int, int] = {}
    for msg in track:
        if msg.type in ("note_on", "note_off"):
            counts[msg.channel] = counts.get(msg.channel, 0) + 1
    if not counts:
        return default
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _strip_pitches(track: mido.MidiTrack, low: int, high: int) -> mido.MidiTrack:
    """指定音域の note_on / note_off を取り除いたトラックを返す。"""
    kept = [
        (tick, msg)
        for tick, msg in _absolute(track)
        if not (msg.type in ("note_on", "note_off") and low <= msg.note <= high)
    ]
    return _to_track(kept)


def build_ks_track(
    rendered: RenderResult,
    channel: int,
    name: str,
) -> mido.MidiTrack:
    """生成された KS / CC からトラックを組み立てる。"""
    entries: list[tuple[int, mido.Message]] = [
        (0, mido.MetaMessage("track_name", name=name, time=0))
    ]

    for cc in rendered.ccs:
        entries.append(
            (
                cc.tick,
                mido.Message(
                    "control_change", channel=channel, control=cc.control, value=cc.value
                ),
            )
        )

    for note in rendered.notes:
        entries.append(
            (
                note.start,
                mido.Message(
                    "note_on", channel=channel, note=note.pitch, velocity=note.velocity
                ),
            )
        )
        entries.append(
            (
                note.end,
                mido.Message("note_off", channel=channel, note=note.pitch, velocity=0),
            )
        )

    keyswitch_pitches = frozenset(n.pitch for n in rendered.notes)
    return _to_track(entries, keyswitch_pitches)


def write(
    path: str | Path,
    source,
    rendered: RenderResult,
    *,
    ks_track_name: str,
    inline: bool = False,
    export: bool = False,
    annotation_block: tuple[int, int] = (105, 127),
) -> None:
    """出力 MIDI を書き出す。

    Parameters
    ----------
    source : SourceMidi
        読み込み結果。トラック構成とテンポ情報の元になる。
    inline
        True なら KS を実音トラックにマージし、単一トラックにする。
    export
        True なら注釈ノート（105–127）を除去する。
    """
    src = source.midi
    out = mido.MidiFile(type=1, ticks_per_beat=source.tpq)
    if src.charset:
        out.charset = src.charset

    target_index = source.target_index
    channel = _dominant_channel(src.tracks[target_index])
    ks_track = build_ks_track(rendered, channel, ks_track_name)

    for i, track in enumerate(src.tracks):
        # 過去の実行で生成した KS トラックは破棄して作り直す
        if _name_of(track) == ks_track_name:
            continue

        if i == target_index:
            current = _strip_pitches(track, *annotation_block) if export else track
            if inline:
                merged = _absolute(current) + _absolute(ks_track)
                keyswitch_pitches = frozenset(n.pitch for n in rendered.notes)
                # KS トラック由来の track_name は捨てる
                merged = [
                    (tick, msg)
                    for tick, msg in merged
                    if not (msg.is_meta and msg.type == "track_name" and msg.name == ks_track_name)
                ]
                current = _to_track(merged, keyswitch_pitches)
            out.tracks.append(current)
        else:
            out.tracks.append(track)

    if not inline:
        out.tracks.append(ks_track)

    out.save(str(path))


def _name_of(track: mido.MidiTrack) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name.split("\x00")[0].strip()
    return ""
