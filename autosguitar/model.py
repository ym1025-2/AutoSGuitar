"""内部データモデル。

仕様は docs/05-architecture.md §5.2 を参照。
すべての音高は MIDI ノート番号（整数）で保持する。ノート名は表示専用
（docs/02-sound-source-spec.md §2.1 の表記系のずれを避けるため）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Articulation(str, Enum):
    """奏法。値は docs/02-sound-source-spec.md §2.3 の ID に対応する。"""

    SUSTAIN = "sustain"
    PALM_MUTE = "palm_mute"
    BRUSH = "brush"
    MUTE_FRET = "mute_fret"
    HAMMER_PULL = "hammer_pull"
    HARMONICS_NATURAL = "harmonics_natural"
    HARMONICS_PINCH = "harmonics_pinch"
    SLIDE_DOWN = "slide_down"
    SLIDE_UP = "slide_up"
    SLIDE_IN = "slide_in"
    SLIDE_OUT = "slide_out"
    BEND_HT = "bend_ht"
    BEND_WT = "bend_wt"
    BEND_1HT = "bend_1ht"


class Stroke(str, Enum):
    DOWN = "down"
    UP = "up"


@dataclass(frozen=True, order=True)
class Note:
    """発音域の実音、あるいは注釈ノート / キースイッチノート。"""

    start: int
    end: int
    pitch: int
    velocity: int

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class GridPos:
    """イベントの拍位置。docs/04-articulation-rules.md §4.1 で使う。"""

    bar: int
    #: 小節先頭からの tick
    tick_in_bar: int
    #: 支配的な分割の 1 単位あたりの tick 数（8分なら tpq/2）
    division: int
    #: 分割内の通し番号。偶数が Down 候補
    slot: int
    #: 強拍か（拍頭にあるか）
    is_strong: bool


@dataclass
class Event:
    """同時発音のまとまり。キースイッチ割り当ての単位。

    和音は 1 イベントとして扱う（KS 1 個が和音全体を支配する:
    docs/02-sound-source-spec.md §2.7 ⑤）。
    """

    start: int
    notes: list[Note]
    grid: GridPos | None = None
    #: 次イベント開始までの間隔。最終イベントでは None
    ioi: int | None = None
    #: 次イベント開始 − 自分の終了。負なら重なっている。最終イベントでは None
    gap: int | None = None
    #: 直前イベント終了から自分の開始まで。先頭イベントでは None
    gap_before: int | None = None
    index: int = -1

    # ---- 派生特徴 ----

    @property
    def end(self) -> int:
        return max(n.end for n in self.notes)

    @property
    def duration(self) -> int:
        return self.end - self.start

    @property
    def polyphony(self) -> int:
        return len(self.notes)

    @property
    def is_monophonic(self) -> bool:
        return len(self.notes) == 1

    @property
    def lowest(self) -> int:
        return min(n.pitch for n in self.notes)

    @property
    def highest(self) -> int:
        return max(n.pitch for n in self.notes)

    @property
    def velocity(self) -> int:
        """代表 velocity。和音では最大値を採る。"""
        return max(n.velocity for n in self.notes)

    @property
    def pitch_classes(self) -> set[int]:
        return {n.pitch % 12 for n in self.notes}

    @property
    def duration_ratio(self) -> float:
        """音価 / IOI。1.0 でレガート、小さいほどスタッカート。

        最終イベントなど IOI が取れない場合は 1.0 を返す（スタッカート判定を
        誤発火させないため）。
        """
        if not self.ioi:
            return 1.0
        return self.duration / self.ioi

    @property
    def is_power_chord(self) -> bool:
        """パワーコードの voicing か。

        ルート・完全5度・オクターブだけで構成される 2〜3 音。
        ルート + 5度（2 音）と、ルート + 5度 + オクターブ（3 音）の
        どちらもギターでは同じパワーコードとして扱われる。
        """
        if not 2 <= len(self.notes) <= 3:
            return False
        root = self.lowest
        intervals = {n.pitch - root for n in self.notes}
        return len(intervals) >= 2 and intervals <= {0, 7, 12, 19, 24}

    @property
    def is_full_chord(self) -> bool:
        """3 種類以上の異なるピッチクラスを含む和音。"""
        return len(self.pitch_classes) >= 3


@dataclass
class Decision:
    """1 イベントに対する最終的な判定結果。"""

    event: Event
    articulation: Articulation
    stroke: Stroke | None = None
    #: このイベントの直前に出す CC。{cc_number: value}
    ccs: dict[int, int] = field(default_factory=dict)
    #: 判定根拠。'annotation:106' / 'rule:pedal_tone' / 'default' など。
    #: docs/05-architecture.md §5.2 のとおり必須項目。
    source: str = "default"
    #: ストロークの判定根拠
    stroke_source: str = ""
    #: 装飾音畳み込みなどで削除した音（Phase 2）
    notes_removed: list[Note] = field(default_factory=list)
    #: ロック区間などで KS を出力しない場合 True
    suppressed: bool = False


@dataclass(frozen=True)
class Annotation:
    """注釈ノート 1 個。docs/03-annotation-layer.md 参照。"""

    start: int
    end: int
    pitch: int
    #: rules.yaml の annotations[pitch] の中身
    spec: dict

    @property
    def length(self) -> int:
        return self.end - self.start

    def covers(self, tick: int) -> bool:
        """[start, end) に発音開始が入るか。"""
        return self.start <= tick < self.end
