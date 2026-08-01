"""注釈レイヤーと優先度チェーンのテスト。docs/03-annotation-layer.md §3.4"""

from __future__ import annotations

from autosguitar import annotation as annotation_mod
from autosguitar.analysis import features, grid, grouping
from autosguitar.midiio.reader import BarMap
from autosguitar.model import Annotation, Articulation, Note, Stroke

from conftest import BAR, E8, TPQ

BAR_MAP = BarMap([(0, 0, BAR, TPQ)])


def build_events(notes):
    events = grouping.group_events(notes, TPQ // 32)
    features.fill_relations(events)
    grid.assign_grid(events, BAR_MAP, [1, 2, 3, 4, 6], TPQ // 16)
    return events


def resolve(events, annotations=(), keyswitches=()):
    return annotation_mod.resolve(
        events,
        list(annotations),
        list(keyswitches),
        chord_tolerance=TPQ // 32,
        ks_max_lead=TPQ // 4,
    )


def run(start, pitches, step):
    return [Note(start + i * step, start + i * step + step, p, 100) for i, p in enumerate(pitches)]


def test_annotation_length_defines_scope():
    """注釈ノートの長さが適用範囲になる（§3.2）。"""
    events = build_events(run(0, [60, 62, 64, 66], E8))
    region = Annotation(0, E8 * 2, 106, {"force": "palm_mute"})
    result = resolve(events, [region])

    assert result.per_event[0].force is Articulation.PALM_MUTE
    assert result.per_event[1].force is Articulation.PALM_MUTE
    assert result.per_event[2].force is None
    assert result.per_event[3].force is None


def test_shorter_annotation_wins():
    """区間注釈の中の 1 音だけを上書きできること（§3.4）。"""
    events = build_events(run(0, [60, 62, 64, 66], E8))
    region = Annotation(0, BAR, 106, {"force": "palm_mute"})
    point = Annotation(E8, E8 + 10, 105, {"force": "sustain"})
    result = resolve(events, [region, point])

    assert result.per_event[0].force is Articulation.PALM_MUTE
    assert result.per_event[1].force is Articulation.SUSTAIN
    assert result.per_event[1].force_source == "annotation:105"
    assert result.per_event[2].force is Articulation.PALM_MUTE


def test_equal_length_conflict_is_reported():
    events = build_events(run(0, [60], E8))
    a = Annotation(0, E8, 105, {"force": "sustain"})
    b = Annotation(0, E8, 106, {"force": "palm_mute"})
    result = resolve(events, [a, b])
    assert any("競合" in w for w in result.warnings)


def test_context_and_stroke_annotations():
    events = build_events(run(0, [60, 62], E8))
    result = resolve(
        events,
        [
            Annotation(0, BAR, 122, {"context": "lead"}),
            Annotation(E8, E8 + 10, 126, {"stroke": "up"}),
        ],
    )
    assert result.per_event[0].context == "lead"
    assert result.per_event[1].context == "lead"
    assert result.per_event[0].stroke is None
    assert result.per_event[1].stroke is Stroke.UP


def test_lock_annotation():
    events = build_events(run(0, [60, 62], E8))
    result = resolve(events, [Annotation(0, E8, 127, {"lock": True})])
    assert result.per_event[0].lock
    assert not result.per_event[1].lock


def test_manual_keyswitch_binds_to_simultaneous_note():
    """同一 tick に置かれた手動 KS がイベントに結びつくこと（§2.7 ①）。"""
    events = build_events(run(0, [60, 62], E8))
    result = resolve(events, keyswitches=[Note(0, 10, 21, 100)])
    assert result.per_event[0].manual_ks == 21
    assert result.per_event[1].manual_ks is None


def test_manual_keyswitch_binds_when_placed_slightly_early():
    """わずかに手前に置かれた手動 KS も結びつくこと（§2.7 ②）。"""
    events = build_events(run(E8, [60], E8))
    result = resolve(events, keyswitches=[Note(E8 - 30, E8, 96, 100)])
    assert result.per_event[0].manual_ks == 96


def test_orphan_manual_keyswitch_is_warned():
    events = build_events(run(0, [60], E8))
    result = resolve(events, keyswitches=[Note(BAR * 4, BAR * 4 + 10, 21, 100)])
    assert result.per_event[0].manual_ks is None
    assert any("見つかりません" in w for w in result.warnings)


def test_unknown_force_value_is_warned():
    events = build_events(run(0, [60], E8))
    result = resolve(events, [Annotation(0, E8, 105, {"force": "nonexistent"})])
    assert result.per_event[0].force is None
    assert any("未知の奏法" in w for w in result.warnings)
