"""判定ルールの単体テスト。docs/04-articulation-rules.md"""

from __future__ import annotations

import pytest

from autosguitar.analysis import features, grid, grouping
from autosguitar.midiio.reader import BarMap, TempoMap
from autosguitar.model import Articulation, Note, Stroke
from autosguitar.rules import dead_note, legato, palm_mute
from autosguitar.rules import stroke as stroke_rules

from conftest import BAR, E8, E16, TPQ, make_settings

BAR_MAP = BarMap([(0, 0, BAR, TPQ)])


def build_events(notes, tolerance=TPQ // 32):
    events = grouping.group_events(notes, tolerance)
    features.fill_relations(events)
    grid.assign_grid(events, BAR_MAP, [1, 2, 3, 4, 6], TPQ // 16)
    return events


def run(start, pitches, step, duration=None, velocity=100):
    duration = step if duration is None else duration
    return [
        Note(start + i * step, start + i * step + duration, p, velocity)
        for i, p in enumerate(pitches)
    ]


# ---------------------------------------------------------------- ペダルトーン


def test_pedal_tone_detection():
    """最低音が 3 回以上かつ 40% 以上を占めればペダルとみなす（§4.2）。"""
    notes = run(0, [35, 35, 42, 35, 35, 40, 35, 38], E8, E8 - 40)
    events = build_events(notes)
    pedal = palm_mute.detect_pedal_tones(events, window_bars=2, min_count=3, min_share=0.40)
    pedal_pitches = {events[i].lowest for i in pedal}
    assert pedal_pitches == {35}
    assert len(pedal) == 5


def test_pedal_tone_not_detected_in_melodic_line():
    """上下する旋律ではペダルは検出されない。"""
    notes = run(0, [60, 62, 64, 65, 67, 65, 64, 62], E8)
    events = build_events(notes)
    pedal = palm_mute.detect_pedal_tones(events, window_bars=2, min_count=3, min_share=0.40)
    assert pedal == set()


def test_pedal_tone_ignores_full_chords():
    """和音の中にたまたま最低音が含まれるだけの場合は除外する。"""
    notes = []
    for i in range(4):
        notes += [
            Note(i * E8, i * E8 + E8, 35, 100),
            Note(i * E8, i * E8 + E8, 47, 100),
            Note(i * E8, i * E8 + E8, 52, 100),
        ]
    events = build_events(notes)
    pedal = palm_mute.detect_pedal_tones(events, window_bars=2, min_count=3, min_share=0.40)
    assert pedal == set()


# ------------------------------------------------------------- パームミュート


def test_palm_mute_low_staccato():
    settings = make_settings()
    events = build_events(run(0, [40, 40, 40, 40], E8, E8 // 3))
    ok, score = palm_mute.is_palm_mute(events[1], events[0], False, None, settings.palm_mute)
    assert ok
    assert score.total >= settings.palm_mute["score_threshold"]


def test_palm_mute_rejected_in_high_register():
    """高音域は強く否定される（§4.2）。"""
    settings = make_settings()
    events = build_events(run(0, [72, 72, 72, 72], E8, E8 // 3))
    ok, _ = palm_mute.is_palm_mute(events[1], events[0], False, None, settings.palm_mute)
    assert not ok


def test_palm_mute_rejected_for_full_chord():
    """3 種類以上のピッチクラスを持つ和音は否定される（§4.2）。"""
    settings = make_settings()
    triad = (45, 49, 52)  # A2 C#3 E3 = A メジャートライアド
    notes = [Note(0, E8 // 2, p, 100) for p in triad] + [
        Note(E8, E8 + E8 // 2, p, 100) for p in triad
    ]
    events = build_events(notes)
    assert events[0].is_full_chord
    ok, _ = palm_mute.is_palm_mute(events[0], None, False, None, settings.palm_mute)
    assert not ok


def test_power_chord_voicings_are_palm_mute_candidates():
    """ルート + 5度 + オクターブの 3 音もパワーコードとして扱う。"""
    settings = make_settings()
    voicing = (45, 52, 57)  # A2 E3 A3
    notes = [Note(0, E8 // 2, p, 100) for p in voicing] + [
        Note(E8, E8 + E8 // 2, p, 100) for p in voicing
    ]
    events = build_events(notes)
    assert events[0].is_power_chord
    assert not events[0].is_full_chord
    ok, _ = palm_mute.is_palm_mute(events[0], None, False, None, settings.palm_mute)
    assert ok


@pytest.mark.parametrize("context", ["lead", "clean"])
def test_palm_mute_vetoed_by_context(context):
    """context 注釈がリード / クリーンならパームミュートを事実上禁止する。"""
    settings = make_settings()
    events = build_events(run(0, [40, 40, 40, 40], E8, E8 // 3))
    ok, _ = palm_mute.is_palm_mute(events[1], events[0], True, context, settings.palm_mute)
    assert not ok


# ---------------------------------------------------------------- デッドノート


def test_dead_note_requires_short_and_quiet():
    settings = make_settings()
    short_quiet = build_events(run(0, [45, 45], E8, 20, velocity=30))[0]
    short_loud = build_events(run(0, [45, 45], E8, 20, velocity=110))[0]
    long_quiet = build_events(run(0, [45, 45], E8, E8, velocity=30))[0]

    assert dead_note.is_dead_note(short_quiet, settings.dead_note)
    assert not dead_note.is_dead_note(short_loud, settings.dead_note)
    assert not dead_note.is_dead_note(long_quiet, settings.dead_note)


def test_dead_note_articulation_depends_on_polyphony():
    single = build_events([Note(0, 20, 45, 30)])[0]
    chord = build_events([Note(0, 20, 45, 30), Note(0, 20, 52, 30)])[0]
    assert dead_note.articulation_for(single) is Articulation.MUTE_FRET
    assert dead_note.articulation_for(chord) is Articulation.BRUSH


# ---------------------------------------------------------------------- レガート


def test_legato_detected_on_overlapping_small_interval():
    settings = make_settings()
    notes = [Note(0, E8 + 30, 67, 100), Note(E8, E8 * 2, 69, 100)]
    events = build_events(notes)
    assert legato.is_legato(events[1], events[0], Articulation.SUSTAIN, settings.legato)


def test_legato_rejected_on_large_interval():
    settings = make_settings()
    notes = [Note(0, E8 + 30, 60, 100), Note(E8, E8 * 2, 72, 100)]
    events = build_events(notes)
    assert not legato.is_legato(events[1], events[0], Articulation.SUSTAIN, settings.legato)


def test_legato_rejected_after_rest():
    """休符明けの音は必ずピッキングされる（§4.4 除外条件）。"""
    settings = make_settings()
    notes = [Note(0, E8, 67, 100), Note(BAR, BAR + E8, 69, 100)]
    events = build_events(notes)
    assert not legato.is_legato(events[1], events[0], Articulation.SUSTAIN, settings.legato)


def test_legato_rejected_after_palm_mute():
    """パームミュート中はレガートしない（§4.4 除外条件）。"""
    settings = make_settings()
    notes = [Note(0, E8 + 30, 67, 100), Note(E8, E8 * 2, 69, 100)]
    events = build_events(notes)
    assert not legato.is_legato(events[1], events[0], Articulation.PALM_MUTE, settings.legato)


def test_legato_rejected_on_repeated_pitch():
    settings = make_settings()
    notes = [Note(0, E8 + 30, 67, 100), Note(E8, E8 * 2, 67, 100)]
    events = build_events(notes)
    assert not legato.is_legato(events[1], events[0], Articulation.SUSTAIN, settings.legato)


# -------------------------------------------------------------------- ストローク


def assign(events, articulations, contexts=None, bpm=120.0, cfg=None):
    settings = make_settings()
    return stroke_rules.assign(
        events,
        articulations,
        contexts or [None] * len(events),
        BAR_MAP,
        TempoMap([(0, int(60_000_000 / bpm))]),
        frozenset({Articulation.SUSTAIN, Articulation.PALM_MUTE}),
        cfg if cfg is not None else settings.stroke,
    )


def test_alternate_picking_on_eighth_grid():
    """8 分グリッドでスロット偶奇どおりに交替すること（§4.1）。"""
    events = build_events(run(0, [64, 66, 67, 69, 71, 69, 67, 66], E8))
    result = assign(events, [Articulation.SUSTAIN] * 8)
    strokes = [r.stroke for r in result]
    assert strokes == [
        Stroke.DOWN, Stroke.UP, Stroke.DOWN, Stroke.UP,
        Stroke.DOWN, Stroke.UP, Stroke.DOWN, Stroke.UP,
    ]


def test_rest_resets_to_downstroke():
    """1 拍以上の休符の後は必ずダウン（§4.1 上書き 1）。"""
    notes = run(0, [64, 66], E8, E8 - 20) + run(E8 * 2 + TPQ, [67, 69], E8, E8 - 20)
    events = build_events(notes)
    result = assign(events, [Articulation.SUSTAIN] * len(events))
    assert result[0].stroke is Stroke.DOWN
    assert result[1].stroke is Stroke.UP
    assert result[2].stroke is Stroke.DOWN
    assert result[2].source == "rule:rest_reset"


def test_downpicking_applies_to_slow_low_palm_mute():
    """低音域のパームミュート 8 分は 170 BPM 以下なら全ダウン（§4.1 上書き 2）。"""
    events = build_events(run(0, [40] * 8, E8, E8 - 40))
    result = assign(events, [Articulation.PALM_MUTE] * 8, bpm=150)
    assert all(r.stroke is Stroke.DOWN for r in result)
    assert result[1].source == "rule:downpick"


def test_downpicking_disabled_when_too_fast():
    """16 分 @150BPM は 8 分換算 300BPM なのでオルタネイトに切り替わる。"""
    events = build_events(run(0, [40] * 16, E16, E16 - 20))
    result = assign(events, [Articulation.PALM_MUTE] * 16, bpm=150)
    assert result[1].stroke is Stroke.UP
    assert result[1].source == "rule:alternate"


def test_downpicking_does_not_corrupt_alternation_phase():
    """ダウンピッキング上書きが後続のオルタネイト位相を汚さないこと。

    ペダル音だけがダウンピッキングされ、旋律音はグリッドどおりに交替する。
    """
    pitches = [35, 35, 42, 35, 35, 40, 35, 38]
    events = build_events(run(0, pitches, E8, E8 - 40))
    articulations = [
        Articulation.PALM_MUTE if p == 35 else Articulation.SUSTAIN for p in pitches
    ]
    result = assign(events, articulations, bpm=150)
    strokes = [r.stroke for r in result]
    # スロット 2 は拍頭なのでダウン、スロット 5 / 7 は裏拍なのでアップ
    assert strokes[2] is Stroke.DOWN
    assert strokes[5] is Stroke.UP
    assert strokes[7] is Stroke.UP


def test_coarse_grid_is_all_downstrokes():
    """4 分音符以上の間隔なら全ダウン（§4.1 上書き 4）。"""
    events = build_events(run(0, [40, 42, 43, 45], TPQ, TPQ - 20))
    result = assign(events, [Articulation.SUSTAIN] * 4)
    assert all(r.stroke is Stroke.DOWN for r in result)


def test_gallop_pattern():
    """8分 + 16分 + 16分 → D, D, U（§4.1 上書き 3）。"""
    notes = [
        Note(0, E8 - 20, 40, 100),
        Note(E8, E8 + E16 - 20, 40, 100),
        Note(E8 + E16, E8 + E16 * 2 - 20, 40, 100),
    ]
    events = build_events(notes)
    overrides = stroke_rules.detect_gallops(events, BAR_MAP)
    assert overrides == {0: Stroke.DOWN, 1: Stroke.DOWN, 2: Stroke.UP}


def test_reverse_gallop_pattern():
    """16分 + 16分 + 8分 → D, U, D。"""
    notes = [
        Note(0, E16 - 20, 40, 100),
        Note(E16, E16 * 2 - 20, 40, 100),
        Note(E16 * 2, E16 * 2 + E8 - 20, 40, 100),
    ]
    events = build_events(notes)
    overrides = stroke_rules.detect_gallops(events, BAR_MAP)
    assert overrides == {0: Stroke.DOWN, 1: Stroke.UP, 2: Stroke.DOWN}


def test_unstroked_articulations_get_no_stroke():
    events = build_events(run(0, [64, 66], E8))
    result = assign(events, [Articulation.HAMMER_PULL, Articulation.BRUSH])
    assert all(r.stroke is None for r in result)
