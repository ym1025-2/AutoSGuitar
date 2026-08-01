"""デッドノート / ブラッシング判定。docs/04-articulation-rules.md §4.3

いわゆる「チャッ」という percussive なゴーストノート。
極端に短く velocity が低い音を対象とする。
"""

from __future__ import annotations

from ..model import Articulation, Event


def is_dead_note(event: Event, cfg: dict) -> bool:
    if event.velocity > cfg.get("max_velocity", 50):
        return False
    short_absolute = event.duration <= cfg.get("max_duration", 0)
    short_relative = event.duration_ratio <= cfg.get("max_duration_ratio", 0.25)
    return short_absolute or short_relative


def articulation_for(event: Event) -> Articulation:
    """単音ならフレットミュート、和音ならブラッシング。"""
    return Articulation.MUTE_FRET if event.is_monophonic else Articulation.BRUSH
