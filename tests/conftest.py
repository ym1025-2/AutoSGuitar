"""テスト用の共通フィクスチャ。"""

from __future__ import annotations

import mido
import pytest

from autosguitar import config, profile as profiles

TPQ = 480
BAR = TPQ * 4
E8 = TPQ // 2
E16 = TPQ // 4


@pytest.fixture
def profile():
    return profiles.get("ksop")


@pytest.fixture
def settings():
    return config.Settings(config.load(), TPQ)


def make_settings(overrides: dict | None = None, tpq: int = TPQ, polish: int = 1):
    cfg = config.load()
    if overrides:
        cfg = config.deep_merge(cfg, overrides)
        cfg = config._normalize_annotation_keys(cfg)
    return config.Settings(cfg, tpq, polish=polish)


class MidiBuilder:
    """テスト用の MIDI を組み立てる小さなヘルパー。"""

    def __init__(self, tpq: int = TPQ, bpm: float = 120.0, numerator: int = 4, denominator: int = 4):
        self.tpq = tpq
        self.events: list[tuple[int, str, int, int]] = []
        self.meta = mido.MidiTrack()
        self.meta.append(mido.MetaMessage("track_name", name="Test", time=0))
        self.meta.append(
            mido.MetaMessage(
                "time_signature", numerator=numerator, denominator=denominator, time=0
            )
        )
        self.meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))

    def note(self, tick: int, pitch: int, duration: int, velocity: int = 100):
        self.events.append((tick, "on", pitch, velocity))
        self.events.append((tick + duration, "off", pitch, 0))
        return self

    def chord(self, tick: int, pitches, duration: int, velocity: int = 100):
        for pitch in pitches:
            self.note(tick, pitch, duration, velocity)
        return self

    def run(self, start: int, pitches, step: int, duration: int | None = None, velocity: int = 100):
        """等間隔の音列を置く。"""
        duration = step if duration is None else duration
        for i, pitch in enumerate(pitches):
            self.note(start + i * step, pitch, duration, velocity)
        return self

    def build(self, track_name: str = "Guitar") -> mido.MidiFile:
        mid = mido.MidiFile(type=1, ticks_per_beat=self.tpq)
        mid.tracks.append(self.meta)
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=track_name, time=0))
        ordered = sorted(self.events, key=lambda e: (e[0], 0 if e[1] == "off" else 1))
        previous = 0
        for tick, kind, pitch, velocity in ordered:
            track.append(
                mido.Message(
                    "note_on" if kind == "on" else "note_off",
                    note=pitch,
                    velocity=velocity,
                    time=tick - previous,
                )
            )
            previous = tick
        mid.tracks.append(track)
        return mid

    def save(self, path, track_name: str = "Guitar"):
        self.build(track_name).save(str(path))
        return path


@pytest.fixture
def builder():
    return MidiBuilder
