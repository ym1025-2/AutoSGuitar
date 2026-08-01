"""コマンドラインインターフェース。docs/05-architecture.md §5.5"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, pipeline, profile as profiles, report
from .midiio import writer
from .notation import DEFAULT_SYSTEM, SYSTEMS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosguitar",
        description="Sforzando Standard Guitar 向けにキースイッチを自動付加します。",
    )
    parser.add_argument("input", type=Path, help="入力 MIDI ファイル")
    parser.add_argument("-o", "--output", type=Path, help="出力 MIDI ファイル")
    parser.add_argument(
        "--profile", default=None, help="音源プロファイル（既定: rules.yaml の profile）"
    )
    parser.add_argument("--rules", type=Path, default=None, help="ルール設定 YAML")
    parser.add_argument(
        "--track", type=int, default=None, help="処理対象トラック番号（既定: 自動選択）"
    )
    parser.add_argument(
        "--polish",
        type=int,
        choices=(0, 1, 2),
        default=1,
        help="出力の仕上げレベル（Phase 1 では 0/1 のみ実装）",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="キースイッチを実音トラックにマージして単一トラックにする",
    )
    parser.add_argument(
        "--export", action="store_true", help="注釈ノート（105–127）を除去する"
    )
    parser.add_argument("--report", type=Path, default=None, help="判定レポートの出力先 CSV")
    parser.add_argument(
        "--note-names",
        choices=sorted(SYSTEMS),
        default=DEFAULT_SYSTEM,
        help="ログ / レポートのノート名表記系（既定: s1 = Studio One 式）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="MIDI を書かずレポートのみ出力する"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="要約を表示しない")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.is_file():
        print(f"入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 2

    if args.output is None and not args.dry_run:
        args.output = args.input.with_name(f"{args.input.stem}_ks{args.input.suffix}")

    try:
        cfg = config.load(args.rules)
    except config.ConfigError as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return 2

    profile_name = args.profile or cfg.get("profile", "ksop")
    try:
        profile = profiles.get(profile_name)
    except KeyError as exc:
        print(f"設定エラー: {exc}", file=sys.stderr)
        return 2

    if args.polish == 2:
        print(
            "警告: --polish 2（ヒューマナイズ / ノイズ FX）は Phase 2 で実装予定です。"
            "1 として処理します。",
            file=sys.stderr,
        )

    try:
        import mido

        tpq = mido.MidiFile(str(args.input)).ticks_per_beat
        settings = config.Settings(cfg, tpq, polish=min(args.polish, 1))
        result = pipeline.process(args.input, settings, profile, track_index=args.track)
    except (config.ConfigError, ValueError, IndexError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    target = result.source.target
    if not args.quiet:
        label = f"（{target.name}）" if target.name else ""
        print(f"対象トラック: {target.index}{label}")
        print(report.summarize(result.decisions, profile, args.note_names))

    for message in result.warnings:
        print(f"[warning] {message}", file=sys.stderr)
    for issue in result.validation.issues:
        print(issue.format(), file=sys.stderr)

    if not result.validation.ok():
        print(
            f"エラーが {len(result.validation.errors)} 件あります。出力を中止しました。",
            file=sys.stderr,
        )
        return 1

    if args.report is not None:
        report.write_csv(args.report, result.decisions, profile, args.note_names)
        if not args.quiet:
            print(f"レポート: {args.report}")

    if args.dry_run:
        if not args.quiet:
            print("--dry-run のため MIDI は書き出していません。")
        return 0

    writer.write(
        args.output,
        result.source,
        result.rendered,
        ks_track_name=settings.ks_track_name,
        inline=args.inline,
        export=args.export,
        annotation_block=settings.annotation_block,
    )
    if not args.quiet:
        print(f"出力: {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
