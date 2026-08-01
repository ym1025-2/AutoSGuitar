"""プロファイル定数の検証。docs/02-sound-source-spec.md との整合を守る。"""

from __future__ import annotations

import pytest

from autosguitar.model import Articulation, Stroke
from autosguitar.notation import note_name
from autosguitar.profile import ksop


def test_ranges_do_not_overlap():
    """発音域・キースイッチ域・注釈ブロックが重ならないこと。"""
    playable = set(range(ksop.PLAYABLE_LOW, ksop.PLAYABLE_HIGH + 1))
    keyswitch = set(range(*ksop.KS_LOW_RANGE)) | set(range(*ksop.KS_HIGH_RANGE))
    annotation = set(range(ksop.ANNOTATION_LOW, ksop.ANNOTATION_HIGH + 1))

    assert not playable & keyswitch
    assert not playable & annotation
    assert not keyswitch & annotation


def test_playable_range_matches_sfz():
    """sfz の lokey=b1 / hikey=d6 と一致すること。"""
    assert ksop.PLAYABLE_LOW == 35
    assert ksop.PLAYABLE_HIGH == 86


def test_annotation_block_above_sw_hikey():
    """sfz の sw_hikey=g#7 (104) より上にあること。"""
    assert ksop.ANNOTATION_LOW == 105
    assert all(not ksop.is_keyswitch(p) for p in range(105, 128))


def test_fretboard_matches_playable_range():
    """7 弦 22 フレットの音域が発音域と一致すること（docs §4.8 の根拠）。"""
    assert min(ksop.OPEN_STRINGS) == ksop.PLAYABLE_LOW
    assert max(ksop.OPEN_STRINGS) + ksop.MAX_FRET == ksop.PLAYABLE_HIGH


def test_alternate_keyswitches_are_never_emitted():
    """オルタネイト KS (26/29) は出力側の割り当てに存在しないこと。"""
    assert 26 not in ksop.ARTICULATION_TO_KS.values()
    assert 29 not in ksop.ARTICULATION_TO_KS.values()


def test_keyswitch_for_ignores_stroke_on_unstroked_articulations():
    assert ksop.keyswitch_for(Articulation.HAMMER_PULL, Stroke.UP) == 30
    assert ksop.keyswitch_for(Articulation.SUSTAIN, Stroke.UP) == 25
    assert ksop.keyswitch_for(Articulation.PALM_MUTE, Stroke.DOWN) == 27


@pytest.mark.parametrize(
    "semitones,expected",
    [(1, 8), (2, 24), (3, 40), (4, 56), (5, 72), (6, 88), (7, 112)],
)
def test_slide_interval_table(semitones, expected):
    """docs §2.6 のスライド距離テーブル。"""
    assert ksop.slide_interval_cc(semitones) == expected


def test_slide_interval_clamps():
    assert ksop.slide_interval_cc(0) == 8
    assert ksop.slide_interval_cc(20) == 112
    assert ksop.slide_interval_cc(-3) == 40


@pytest.mark.parametrize(
    "pitch,s1,manual",
    [
        (11, "B-2", "B-1"),
        (24, "C0", "C1"),
        (35, "B0", "B1"),
        (60, "C3", "C4"),
        (86, "D5", "D6"),
        (105, "A6", "A7"),
        (127, "G8", "G9"),
    ],
)
def test_note_name_systems(pitch, s1, manual):
    """docs §2.1 の換算表。Studio One 表記はマニュアルより 1 オクターブ低い。"""
    assert note_name(pitch, "s1") == s1
    assert note_name(pitch, "manual") == manual
