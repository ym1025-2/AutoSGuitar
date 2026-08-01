"""パイプラインの組み立て。docs/05-architecture.md §5.1

    Parse → Split → Group → Featurize → Annotate → RuleEngine → Render → Validate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import annotation as annotation_mod
from . import render as render_mod
from . import validate as validate_mod
from .analysis import features, grid, grouping
from .midiio import reader
from .model import Decision, Event
from .rules import engine


@dataclass
class ProcessResult:
    source: reader.SourceMidi
    events: list[Event]
    decisions: list[Decision]
    rendered: render_mod.RenderResult
    validation: validate_mod.ValidationResult
    warnings: list[str] = field(default_factory=list)


def process(
    path: str | Path,
    settings,
    profile,
    track_index: int | None = None,
) -> ProcessResult:
    source = reader.read(
        path,
        profile,
        annotation_block=settings.annotation_block,
        track_index=track_index,
        ks_track_name=settings.ks_track_name,
    )
    target = source.target

    annotations, unknown = reader.build_annotations(target.annotations_raw, settings)

    events = grouping.group_events(target.playable, settings.chord_tolerance)
    features.fill_relations(events)
    grid.assign_grid(
        events,
        source.bar_map,
        settings.subdivision_candidates,
        settings.grid_tolerance,
    )

    resolution = annotation_mod.resolve(
        events,
        annotations,
        target.keyswitches,
        chord_tolerance=settings.chord_tolerance,
        # 手動 KS は実音と同一 tick か、わずかに手前に置かれる（§2.7）
        ks_max_lead=max(settings.ks_lead * 4, settings.tpq // 4),
    )

    decisions = engine.decide(
        events,
        resolution.per_event,
        engine.EngineContext(
            bar_map=source.bar_map,
            tempo_map=source.tempo_map,
            profile=profile,
            settings=settings,
        ),
    )

    rendered = render_mod.render(decisions, profile, settings)

    validation = validate_mod.validate(
        events,
        decisions,
        rendered,
        target.out_of_range,
        unknown,
        profile,
    )

    return ProcessResult(
        source=source,
        events=events,
        decisions=decisions,
        rendered=rendered,
        validation=validation,
        warnings=resolution.warnings,
    )
