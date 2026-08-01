"""パイプライン全体と出力 MIDI の構造検証。

Sforzando は VST のみで音による自動回帰テストができないため、
出力 MIDI をパースし直した構造テストを主軸に据える
（docs/05-architecture.md §5.8）。
"""

from __future__ import annotations

import mido
import pytest

from autosguitar import pipeline, profile as profiles
from autosguitar.midiio import reader, writer
from autosguitar.model import Articulation, Stroke

from conftest import BAR, E8, E16, TPQ, MidiBuilder, make_settings

KSOP = profiles.get("ksop")


def process(path, overrides=None, track_index=None):
    settings = make_settings(overrides)
    return settings, pipeline.process(path, settings, KSOP, track_index=track_index)


def riff_midi(tmp_path, name="riff.mid"):
    """B1 ペダルのパームミュートリフ 2 小節 + 高音レガート 1 小節。"""
    b = MidiBuilder(bpm=150)
    melody = [35, 35, 42, 35, 35, 40, 35, 38]
    for bar in range(2):
        for i, pitch in enumerate(melody):
            b.note(bar * BAR + i * E8, pitch, E8 - 40)
    lead = [67, 69, 71, 69, 67, 64, 67, 71]
    for i, pitch in enumerate(lead):
        b.note(2 * BAR + i * E8, pitch, E8 + 20)
    return b.save(tmp_path / name)


# ------------------------------------------------------------------ 構造検証


def test_output_has_separate_ks_track(tmp_path):
    settings, result = process(riff_midi(tmp_path))
    out = tmp_path / "out.mid"
    writer.write(out, result.source, result.rendered, ks_track_name=settings.ks_track_name)

    mid = mido.MidiFile(str(out))
    assert mid.type == 1
    assert mid.ticks_per_beat == TPQ
    names = [_track_name(t) for t in mid.tracks]
    assert names[-1] == "AutoSG_KS"
    assert "Guitar" in names


def test_generated_notes_are_all_keyswitches(tmp_path):
    _, result = process(riff_midi(tmp_path))
    for note in result.rendered.notes:
        assert KSOP.is_keyswitch(note.pitch)
        assert not KSOP.is_playable(note.pitch)


def test_keyswitches_lead_their_target_note(tmp_path):
    """全 KS が対応する実音以前に置かれること（docs §2.8）。"""
    settings, result = process(riff_midi(tmp_path))
    for note in result.rendered.notes:
        if note.is_release:
            continue
        assert note.start <= note.target_start
        if note.target_start >= settings.ks_lead:
            assert note.target_start - note.start == settings.ks_lead


def test_input_track_is_preserved_verbatim(tmp_path):
    """実音トラックはツールに書き換えられないこと。"""
    src_path = riff_midi(tmp_path)
    settings, result = process(src_path)
    out = tmp_path / "out.mid"
    writer.write(out, result.source, result.rendered, ks_track_name=settings.ks_track_name)

    before = reader.read(src_path, KSOP).target.playable
    after = reader.read(out, KSOP).target.playable
    assert before == after


def test_cc_defaults_are_written_once(tmp_path):
    settings, result = process(riff_midi(tmp_path))
    ccs = result.rendered.ccs
    for control, value in settings.cc_defaults.items():
        matching = [c for c in ccs if c.control == control]
        assert len(matching) == 1, f"CC{control} が {len(matching)} 回書かれています"
        assert matching[0].value == value


def test_cc24_enables_auto_slide_out(tmp_path):
    """既定で自動スライドアウトが有効になること（docs §2.5）。"""
    settings, _ = process(riff_midi(tmp_path))
    assert settings.cc_defaults[24] >= KSOP.CC24_AUTO_SLIDE_OUT_MIN


def test_no_validation_errors(tmp_path):
    _, result = process(riff_midi(tmp_path))
    assert result.validation.ok(), [i.format() for i in result.validation.errors]


def test_polish_0_omits_stroke_differentiation(tmp_path):
    """雛形レベルではダウン / アップを打ち分けない（docs §1.6）。"""
    path = riff_midi(tmp_path)
    draft = pipeline.process(path, make_settings(polish=0), KSOP)
    standard = pipeline.process(path, make_settings(polish=1), KSOP)

    assert all(d.stroke is None for d in draft.decisions)
    assert any(d.stroke is Stroke.UP for d in standard.decisions)
    # 雛形ではアップ用の KS (25 / 28) が出ない
    assert not {n.pitch for n in draft.rendered.notes} & {25, 28}
    assert {n.pitch for n in standard.rendered.notes} & {25, 28}
    # CC 既定値は雛形でも書かれる（CC24 の自動スライドアウトは中核機能のため）
    assert any(c.control == 24 for c in draft.rendered.ccs)


# -------------------------------------------------------------------- 冪等性


def test_rerunning_regenerates_ks_track(tmp_path):
    """出力を再入力しても KS トラックが増えず、内容が一致すること（§3.5）。"""
    settings, first = process(riff_midi(tmp_path))
    out1 = tmp_path / "out1.mid"
    writer.write(out1, first.source, first.rendered, ks_track_name=settings.ks_track_name)

    settings2, second = process(out1)
    out2 = tmp_path / "out2.mid"
    writer.write(out2, second.source, second.rendered, ks_track_name=settings2.ks_track_name)

    assert len(mido.MidiFile(str(out1)).tracks) == len(mido.MidiFile(str(out2)).tracks)
    assert first.rendered.notes == second.rendered.notes
    assert first.rendered.ccs == second.rendered.ccs


def test_inline_merges_into_single_track(tmp_path):
    settings, result = process(riff_midi(tmp_path))
    out = tmp_path / "inline.mid"
    writer.write(
        out, result.source, result.rendered, ks_track_name=settings.ks_track_name, inline=True
    )

    mid = mido.MidiFile(str(out))
    assert "AutoSG_KS" not in [_track_name(t) for t in mid.tracks]
    target = reader.read(out, KSOP).target
    assert target.playable
    assert target.keyswitches


def test_inline_puts_keyswitch_before_note_at_same_tick(tmp_path):
    """マージ時に同一 tick では KS が実音より先に出ること（§2.7 ①）。"""
    settings = make_settings({"render": {"ks_lead": 0}})
    result = pipeline.process(riff_midi(tmp_path), settings, KSOP)
    out = tmp_path / "inline0.mid"
    writer.write(
        out, result.source, result.rendered, ks_track_name=settings.ks_track_name, inline=True
    )

    mid = mido.MidiFile(str(out))
    track = max(mid.tracks, key=len)
    tick = 0
    seen_playable_at: dict[int, bool] = {}
    for msg in track:
        tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            if KSOP.is_playable(msg.note):
                seen_playable_at[tick] = True
            elif KSOP.is_keyswitch(msg.note):
                assert not seen_playable_at.get(tick), (
                    f"tick {tick} でキースイッチ {msg.note} が実音より後に出ています"
                )


# ------------------------------------------------------------------ 注釈の反映


def test_annotation_forces_articulation(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40, 40, 40], E8, E8 - 40)
    b.note(0, 110, BAR)  # force: harmonics_pinch を小節全体に
    path = b.save(tmp_path / "annotated.mid")

    _, result = process(path)
    assert all(d.articulation is Articulation.HARMONICS_PINCH for d in result.decisions)
    assert all(d.source == "annotation:110" for d in result.decisions)
    assert all(n.pitch == 21 for n in result.rendered.notes)


def test_annotation_stroke_override(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40, 40, 40], E8, E8 - 40)
    b.note(0, 126, BAR)  # stroke: up
    path = b.save(tmp_path / "stroke.mid")

    _, result = process(path)
    assert all(d.stroke is Stroke.UP for d in result.decisions)
    assert all(d.stroke_source == "annotation:126" for d in result.decisions)


def test_lock_suppresses_output(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40, 40, 40], E8, E8 - 40)
    b.note(0, 127, E8 * 2)  # 前半 2 音をロック
    path = b.save(tmp_path / "locked.mid")

    _, result = process(path)
    assert [d.suppressed for d in result.decisions] == [True, True, False, False]
    assert len(result.rendered.notes) == 2


def test_manual_keyswitch_is_not_duplicated(tmp_path):
    """入力にある手動 KS はそのまま残るので、ツールは重複して出さない（§3.4）。"""
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40], E8, E8 - 40)
    b.note(0, 21, 10)  # 手動でピッキングハーモニクス
    path = b.save(tmp_path / "manual.mid")

    _, result = process(path)
    assert result.decisions[0].suppressed
    assert result.decisions[0].source == "manual_ks:21"
    assert result.decisions[0].articulation is Articulation.HARMONICS_PINCH
    assert not result.decisions[1].suppressed
    assert len(result.rendered.notes) == 1


def test_export_strips_annotation_notes(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40, 40, 40], E8, E8 - 40)
    b.note(0, 122, BAR)
    path = b.save(tmp_path / "ann.mid")

    settings, result = process(path)
    out = tmp_path / "exported.mid"
    writer.write(
        out,
        result.source,
        result.rendered,
        ks_track_name=settings.ks_track_name,
        export=True,
        annotation_block=settings.annotation_block,
    )
    assert not reader.read(out, KSOP).target.annotations_raw


def test_unknown_annotation_note_warns(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40], E8, E8 - 40)
    b.note(0, 119, BAR)  # 予約済みで未定義
    path = b.save(tmp_path / "unknown.mid")

    _, result = process(path)
    assert any("対応する定義" in i.message for i in result.validation.warnings)


# ------------------------------------------------------------------ 検証機能


def test_out_of_range_notes_are_warned(tmp_path):
    b = MidiBuilder(bpm=120)
    b.run(0, [40, 40, 40], E8, E8 - 40)
    # 87–90 は発音域(≤86)とキースイッチ域(≥91)の間の緩衝帯。発音しない
    b.note(E8 * 3, 90, E8)
    path = b.save(tmp_path / "range.mid")

    _, result = process(path)
    assert any("発音域" in i.message for i in result.validation.warnings)


def test_unplayable_chord_is_warned(tmp_path):
    b = MidiBuilder(bpm=120)
    # 同一弦でしか押さえられない密集した低音クラスター
    b.chord(0, [35, 36, 37, 38], TPQ)
    b.run(TPQ, [40, 42], E8, E8 - 40)
    path = b.save(tmp_path / "chord.mid")

    _, result = process(path)
    assert any("和音" in i.message for i in result.validation.warnings)


# ----------------------------------------------------------- 実データでの通し


def test_runs_on_vendor_demo():
    """メーカー製デモ MIDI で例外なく通ること。無ければスキップ。"""
    from pathlib import Path

    demo = (
        Path(__file__).resolve().parents[1]
        / ".references"
        / "Standard Guitar_Manual"
        / "Sample_MIDI_Files"
        / "Demo_Tracks"
        / "Standard_Guitar_Demo.mid"
    )
    if not demo.is_file():
        pytest.skip("参照用サンプル MIDI がありません")

    settings = make_settings(tpq=mido.MidiFile(str(demo)).ticks_per_beat)
    result = pipeline.process(demo, settings, KSOP)
    assert result.decisions
    assert result.validation.ok(), [i.format() for i in result.validation.errors]
    # デモには手動 KS が大量に置かれているので、その分は抑制されるはず
    assert any(d.suppressed for d in result.decisions)


def _track_name(track) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name.split("\x00")[0].strip()
    return ""
