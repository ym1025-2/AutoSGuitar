"""判定レポートの出力。docs/05-architecture.md §5.2

「なぜこの KS になったのか」を追跡できることが、注釈による往復ワークフローの
前提になる。source 列は必ず埋める。
"""

from __future__ import annotations

import csv
from pathlib import Path

from .model import Decision
from .notation import labelled, note_name

COLUMNS = [
    "index",
    "bar",
    "tick",
    "division",
    "slot",
    "pitches",
    "velocity",
    "articulation",
    "keyswitch",
    "keyswitch_name",
    "stroke",
    "source",
    "stroke_source",
    "ccs",
    "suppressed",
]


def build_rows(decisions: list[Decision], profile, system: str) -> list[dict]:
    rows: list[dict] = []
    for i, decision in enumerate(decisions):
        event = decision.event
        grid = event.grid

        if decision.suppressed:
            ks_pitch: int | None = None
            ks_name = ""
        else:
            ks_pitch = profile.keyswitch_for(decision.articulation, decision.stroke)
            ks_name = profile.KEYSWITCHES.get(ks_pitch, "")

        rows.append(
            {
                "index": i,
                "bar": grid.bar + 1 if grid else "",
                "tick": event.start,
                "division": grid.division if grid else "",
                "slot": grid.slot if grid else "",
                "pitches": " ".join(note_name(n.pitch, system) for n in event.notes),
                "velocity": event.velocity,
                "articulation": decision.articulation.value,
                "keyswitch": ks_pitch if ks_pitch is not None else "",
                "keyswitch_name": ks_name,
                "stroke": decision.stroke.value if decision.stroke else "",
                "source": decision.source,
                "stroke_source": decision.stroke_source,
                "ccs": " ".join(f"CC{c}={v}" for c, v in sorted(decision.ccs.items())),
                "suppressed": "yes" if decision.suppressed else "",
            }
        )
    return rows


def write_csv(path: str | Path, decisions: list[Decision], profile, system: str) -> None:
    rows = build_rows(decisions, profile, system)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def summarize(decisions: list[Decision], profile, system: str) -> str:
    """標準出力向けの要約。"""
    from collections import Counter

    emitted = [d for d in decisions if not d.suppressed]
    articulations = Counter(d.articulation.value for d in emitted)
    strokes = Counter(d.stroke.value for d in emitted if d.stroke)
    sources = Counter(d.source.split("(")[0] for d in emitted)

    lines = [f"イベント数: {len(decisions)}（キースイッチ生成: {len(emitted)}）"]

    lines.append("  奏法:")
    for name, count in articulations.most_common():
        ks = profile.ARTICULATION_TO_KS.get((_articulation(name), None))
        suffix = f"  → KS {labelled(ks, system)}" if ks else ""
        lines.append(f"    {name:<20} {count:>6}{suffix}")

    if strokes:
        lines.append("  ストローク:")
        for name, count in strokes.most_common():
            lines.append(f"    {name:<20} {count:>6}")

    lines.append("  判定根拠:")
    for name, count in sources.most_common():
        lines.append(f"    {name:<20} {count:>6}")

    return "\n".join(lines)


def _articulation(value: str):
    from .model import Articulation

    return Articulation(value)
