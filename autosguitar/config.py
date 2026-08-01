"""ルール設定の読み込みと解決。

`rules.default.yaml` を土台に、ユーザー指定の YAML を再帰マージする。
"tpq/32" のような文字列は入力 MIDI の分解能から tick 数に解決する。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.default.yaml")

_TPQ_EXPR = re.compile(r"^\s*tpq\s*(?:([*/])\s*([0-9]+(?:\.[0-9]+)?))?\s*$", re.IGNORECASE)


class ConfigError(ValueError):
    """設定ファイルの内容が不正な場合に送出する。"""


def resolve_ticks(value: Any, tpq: int) -> int:
    """"tpq/32" のような指定を tick 数に解決する。

    整数・浮動小数はそのまま tick として扱う。
    """
    if isinstance(value, bool):
        raise ConfigError(f"tick 指定に真偽値は使えません: {value!r}")
    if isinstance(value, (int, float)):
        return int(round(value))
    if isinstance(value, str):
        m = _TPQ_EXPR.match(value)
        if m:
            op, operand = m.group(1), m.group(2)
            if op is None:
                return tpq
            n = float(operand)
            if op == "/":
                if n == 0:
                    raise ConfigError(f"0 では割れません: {value!r}")
                return int(round(tpq / n))
            return int(round(tpq * n))
    raise ConfigError(f"tick 指定として解釈できません: {value!r}（例: 30, \"tpq/32\"）")


def deep_merge(base: dict, override: dict) -> dict:
    """override を base の上に再帰的に重ねた新しい dict を返す。"""
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _normalize_annotation_keys(cfg: dict) -> dict:
    """annotations / defaults のキーを int に正規化する。

    YAML はキーを int で読むが、ユーザーが "105" と書く場合に備える。
    """
    for section in ("annotations", "defaults"):
        raw = cfg.get(section)
        if not isinstance(raw, dict):
            continue
        normalized: dict[int, Any] = {}
        for key, value in raw.items():
            try:
                normalized[int(key)] = value
            except (TypeError, ValueError):
                raise ConfigError(
                    f"{section} のキーは MIDI ノート番号 / CC 番号である必要があります: {key!r}"
                ) from None
        cfg[section] = normalized
    return cfg


def load(path: str | Path | None = None) -> dict:
    """既定設定を読み、`path` が指定されていれば重ねて返す。"""
    with DEFAULT_RULES_PATH.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    if path is not None:
        user_path = Path(path)
        if not user_path.is_file():
            raise ConfigError(f"ルールファイルが見つかりません: {user_path}")
        with user_path.open(encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
        if not isinstance(user_cfg, dict):
            raise ConfigError(f"ルールファイルの最上位はマッピングである必要があります: {user_path}")
        cfg = deep_merge(cfg, user_cfg)

    return _normalize_annotation_keys(cfg)


class Settings:
    """設定への型付きアクセス。tick 系の値は tpq で解決済みにする。"""

    def __init__(self, cfg: dict, tpq: int, polish: int = 1):
        self.raw = cfg
        self.tpq = tpq
        #: 出力の仕上げレベル（docs/01-overview.md §1.6）
        self.polish = polish

        self.profile_name: str = cfg.get("profile", "ksop")
        self.annotations: dict[int, dict] = cfg.get("annotations", {})
        self.cc_defaults: dict[int, int] = cfg.get("defaults", {})

        block = cfg.get("annotation_block", [105, 127])
        self.annotation_block: tuple[int, int] = (int(block[0]), int(block[1]))

        render = cfg.get("render", {})
        self.ks_lead: int = resolve_ticks(render.get("ks_lead", "tpq/32"), tpq)
        self.ks_velocity: int = int(render.get("ks_velocity", 100))
        self.dedup: bool = bool(render.get("dedup", False))
        self.ks_track_name: str = render.get("ks_track_name", "AutoSG_KS")

        analysis = cfg.get("analysis", {})
        self.chord_tolerance: int = resolve_ticks(analysis.get("chord_tolerance", "tpq/32"), tpq)
        self.subdivision_candidates: list[int] = list(
            analysis.get("subdivision_candidates", [1, 2, 3, 4, 6])
        )
        self.grid_tolerance: int = resolve_ticks(analysis.get("grid_tolerance", "tpq/16"), tpq)

        rules = cfg.get("rules", {})
        self.stroke: dict = rules.get("stroke", {})
        self.palm_mute: dict = rules.get("palm_mute", {})
        self.dead_note: dict = dict(rules.get("dead_note", {}))
        self.legato: dict = dict(rules.get("legato", {}))

        # tick 指定を含む項目を解決しておく
        self.dead_note["max_duration"] = resolve_ticks(
            self.dead_note.get("max_duration", "tpq/8"), tpq
        )
        self.legato["max_gap"] = resolve_ticks(self.legato.get("max_gap", "tpq/32"), tpq)

    def annotation_spec(self, pitch: int) -> dict | None:
        return self.annotations.get(pitch)
