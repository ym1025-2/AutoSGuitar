"""KSOP プロファイル定数。

出典はすべて docs/02-sound-source-spec.md。値を変更する場合は
必ずドキュメント側も更新すること。
"""

from __future__ import annotations

from ..model import Articulation, Stroke

NAME = "ksop"

# ---------------------------------------------------------------- 音域 (§2.2)

#: 発音域。sfz の lokey=b1 / hikey=d6 に対応
PLAYABLE_LOW = 35
PLAYABLE_HIGH = 86

#: キースイッチ領域
KS_LOW_RANGE = (11, 34)
KS_HIGH_RANGE = (91, 102)

#: 注釈ブロック。sfz の sw_hikey=g#7 (104) より上で完全に未使用
ANNOTATION_LOW = 105
ANNOTATION_HIGH = 127


def is_playable(pitch: int) -> bool:
    return PLAYABLE_LOW <= pitch <= PLAYABLE_HIGH


def is_keyswitch(pitch: int) -> bool:
    return (
        KS_LOW_RANGE[0] <= pitch <= KS_LOW_RANGE[1]
        or KS_HIGH_RANGE[0] <= pitch <= KS_HIGH_RANGE[1]
    )


def is_annotation(pitch: int) -> bool:
    return ANNOTATION_LOW <= pitch <= ANNOTATION_HIGH


# ------------------------------------------------------- キースイッチ (§2.3)

#: MIDI ノート番号 → ID
KEYSWITCHES: dict[int, str] = {
    11: "stop_key",
    12: "hello",
    13: "open_noise",
    14: "hit",
    15: "fret_noise",
    16: "fret_noise2",
    17: "pick_scratch",
    18: "slide_fx",
    19: "slide_fx2",
    20: "harmonics_natural",
    21: "harmonics_pinch",
    22: "brush",
    23: "mute_fret",
    24: "sus_down",
    25: "sus_up",
    26: "sus_alt",
    27: "mute_down",
    28: "mute_up",
    29: "mute_alt",
    30: "hammer_pull",
    31: "slide_down",
    32: "slide_up",
    33: "slide_in",
    34: "slide_out",
    91: "bend_ht",
    92: "bend_wt",
    93: "bend_1ht",
    94: "unison_bend_auto",
    95: "unison_bend_manual",
    96: "portamento",
    97: "sus_pbr12",
    98: "sus_pbr24",
    99: "trill_ht",
    100: "trill_wt",
    101: "trill_min3",
    102: "trill_maj3",
}

#: 音源既定のキースイッチ (sfz の sw_default=c1)
DEFAULT_KEYSWITCH = 24

#: 余韻の強制停止
STOP_KEY = 11

#: (Articulation, Stroke|None) → キースイッチのノート番号。
#:
#: オルタネイト KS (26 / 29) は意図的に使わない。ラウンドロビンが自動復帰せず
#: 「ダウンで始まりアップで終わる」構成を強いられるため
#: (docs/02-sound-source-spec.md §2.9, docs/04-articulation-rules.md §4.1)。
ARTICULATION_TO_KS: dict[tuple[Articulation, Stroke | None], int] = {
    (Articulation.SUSTAIN, Stroke.DOWN): 24,
    (Articulation.SUSTAIN, Stroke.UP): 25,
    (Articulation.SUSTAIN, None): 24,
    (Articulation.PALM_MUTE, Stroke.DOWN): 27,
    (Articulation.PALM_MUTE, Stroke.UP): 28,
    (Articulation.PALM_MUTE, None): 27,
    (Articulation.BRUSH, None): 22,
    (Articulation.MUTE_FRET, None): 23,
    (Articulation.HAMMER_PULL, None): 30,
    (Articulation.HARMONICS_NATURAL, None): 20,
    (Articulation.HARMONICS_PINCH, None): 21,
    (Articulation.SLIDE_DOWN, None): 31,
    (Articulation.SLIDE_UP, None): 32,
    (Articulation.SLIDE_IN, None): 33,
    (Articulation.SLIDE_OUT, None): 34,
    (Articulation.BEND_HT, None): 91,
    (Articulation.BEND_WT, None): 92,
    (Articulation.BEND_1HT, None): 93,
}

#: ダウン / アップの打ち分けを持つ奏法
STROKED_ARTICULATIONS = frozenset({Articulation.SUSTAIN, Articulation.PALM_MUTE})

#: 実音より後ろ（リリース側）に配置するキースイッチ
#: (docs/02-sound-source-spec.md §2.7 ③)
RELEASE_ARTICULATIONS = frozenset({Articulation.SLIDE_OUT})


#: 入力に置かれた手動キースイッチを解釈するための逆引き。
#: オルタネイト KS はツールからは出さないが、ユーザーが置いた場合は解釈する。
KS_TO_ARTICULATION: dict[int, tuple[Articulation, Stroke | None]] = {
    20: (Articulation.HARMONICS_NATURAL, None),
    21: (Articulation.HARMONICS_PINCH, None),
    22: (Articulation.BRUSH, None),
    23: (Articulation.MUTE_FRET, None),
    24: (Articulation.SUSTAIN, Stroke.DOWN),
    25: (Articulation.SUSTAIN, Stroke.UP),
    26: (Articulation.SUSTAIN, None),
    27: (Articulation.PALM_MUTE, Stroke.DOWN),
    28: (Articulation.PALM_MUTE, Stroke.UP),
    29: (Articulation.PALM_MUTE, None),
    30: (Articulation.HAMMER_PULL, None),
    31: (Articulation.SLIDE_DOWN, None),
    32: (Articulation.SLIDE_UP, None),
    33: (Articulation.SLIDE_IN, None),
    34: (Articulation.SLIDE_OUT, None),
    91: (Articulation.BEND_HT, None),
    92: (Articulation.BEND_WT, None),
    93: (Articulation.BEND_1HT, None),
}


def keyswitch_for(articulation: Articulation, stroke: Stroke | None) -> int:
    """奏法とストロークからキースイッチのノート番号を引く。"""
    if articulation not in STROKED_ARTICULATIONS:
        stroke = None
    try:
        return ARTICULATION_TO_KS[(articulation, stroke)]
    except KeyError:  # pragma: no cover - 定義漏れの検出用
        raise KeyError(
            f"KSOP プロファイルに {articulation.value} / {stroke} の割り当てがありません"
        ) from None


# --------------------------------------------------- コントロールチェンジ (§2.4)

CC_LABELS: dict[int, str] = {
    20: "Vib_Depth",
    21: "Vib_Speed",
    22: "Mute_Time",
    23: "Long",
    24: "Rel_Shape",
    25: "Rel_Level",
    26: "Interval_A",
    27: "Interval_B",
    28: "Bend_Time",
    29: "Resonance",
    30: "Picking",
    31: "Micro",
    32: "Sus_P5",
    48: "Magnet",
    52: "Bend_Start",
    53: "Bend_Speed",
    111: "Slide_Speed",
    112: "Trill_Speed",
}

#: sfz の <control> set_ccNN で定義されている音源側の既定値
SFZ_DEFAULTS: dict[int, int] = {
    20: 0,
    21: 95,
    22: 127,
    23: 0,
    24: 13,
    25: 108,
    26: 19,
    27: 82,
    28: 44,
    29: 44,
    30: 75,
    31: 64,
    32: 0,
    48: 64,
    52: 0,
    53: 0,
}

#: スライド距離（半音数）→ CC26 / CC27 の推奨出力値 (§2.6)。
#: 各値域の中央付近を採り、DAW 側の丸めによる誤爆を避ける。
SLIDE_INTERVAL_CC: dict[int, int] = {
    1: 8,  # 半音
    2: 24,  # 1音
    3: 40,  # 1音半
    4: 56,  # 2音
    5: 72,  # 2音半
    6: 88,  # 3音
    7: 112,  # 3音半
}

CC_INTERVAL_A = 26  # スライドアップ / ダウン
CC_INTERVAL_B = 27  # スライドイン

#: CC24 がこの値以上なら音源側が自動スライドアウトを行う (§2.5)
CC24_AUTO_SLIDE_OUT_MIN = 80
#: CC24 がこの値以上なら音源側が自動オルタネイトを行う (§2.5)
CC24_AUTO_ALTERNATE_MIN = 96


def slide_interval_cc(semitones: int) -> int:
    """スライド距離（半音数）を CC 値に変換する。範囲外はクランプする。"""
    clamped = max(1, min(7, abs(semitones)))
    return SLIDE_INTERVAL_CC[clamped]


# ------------------------------------------------------------ フレットボード (§4.8)

#: 7 弦標準チューニングの開放弦（1 弦 → 7 弦の順ではなく低音側から）。
#: 最高音 64 + 22 フレット = 86 が sfz の hikey=d6 と一致する。
OPEN_STRINGS = (35, 40, 45, 50, 55, 59, 64)
MAX_FRET = 22
MAX_POLYPHONY = len(OPEN_STRINGS)
