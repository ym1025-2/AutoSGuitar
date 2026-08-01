# 05. アーキテクチャ

## 5.1 パイプライン

```
in.mid
  │
  ├─ Parse        mido → 内部モデル（絶対 tick + テンポマップ + 拍位置）
  ├─ Split        実音 / 既存 KS / 注釈ノート(105–127) を分離
  ├─ Group        同時発音を Event（単音 or 和音）にまとめる
  ├─ Featurize    拍位置・音価比・IOI・gap・音程・重なり・velocity・音域・声部数
  ├─ Annotate     注釈を Event に解決（優先度チェーン §03-3.4）
  ├─ RuleEngine   各 Event に Articulation + Stroke を付与（§04）
  ├─ Render       Profile(KSOP) に従い KS ノート / CC を生成、配置規則を適用
  ├─ Validate     発音域・KS 衝突・イベント順序を検査
  │
  ├─▶ out.mid     [Guitar] + [AutoSG_KS]
  └─▶ report      判定根拠つき CSV / JSON
```

各段は純関数として実装し、単体でテスト可能にする。

## 5.2 データモデル

```python
@dataclass(frozen=True)
class Note:
    start: int          # 絶対 tick
    end: int
    pitch: int
    velocity: int

@dataclass
class GridPos:
    bar: int
    beat: int
    subdivision: int    # 2=8分, 4=16分, 3=3連 …（小節ごとに推定）
    slot: int           # 分割内の通し番号。偶数=Down 候補
    is_strong: bool

@dataclass
class Event:
    """同時発音のまとまり。KS 割り当ての単位。"""
    start: int
    notes: list[Note]
    grid: GridPos
    ioi: int | None     # 次イベントまでの間隔
    gap: int | None     # 次イベント開始 − 自分の終了（休符長）
    # 派生特徴は property で持つ
    # polyphony / lowest / highest / duration_ratio / interval_to_next …

@dataclass
class Decision:
    event: Event
    articulation: Articulation      # Enum。§02-2.3 の ID に対応
    stroke: Stroke | None           # DOWN / UP / None
    ccs: dict[int, int]             # このイベント直前に出す CC
    source: str                     # 'annotation:106' / 'rule:pedal_tone' / 'default'
    notes_removed: list[Note]       # 装飾音畳み込みなどで削除した音
```

**`Decision.source` は必須。** 「なぜこの KS になったのか」を追跡できることが、
注釈による往復ワークフローの前提になる。判定レポートに必ず出力する。

## 5.3 モジュール構成

```
autosguitar/
├── __init__.py
├── cli.py                  # エントリポイント（引数処理と表示のみ）
├── pipeline.py             # §5.1 の各段の組み立て
├── config.py               # rules.yaml の読み込み・マージ・tpq 解決
├── model.py                # Note / Event / Decision / Annotation / Articulation
├── notation.py             # ノート名の表示（§02-2.1 の表記系）
├── profile/
│   ├── __init__.py
│   └── ksop.py             # §02 の定数テーブル（KS マップ / CC / 音域 / 弦）
├── midiio/                 # `io` は標準ライブラリと紛らわしいため midiio
│   ├── __init__.py
│   ├── reader.py           # mido → Note[] + テンポマップ + 小節マップ
│   └── writer.py           # RenderResult → MidiFile
├── analysis/
│   ├── __init__.py
│   ├── grid.py             # 拍・分割推定、スナップ
│   ├── grouping.py         # 同時発音の Event 化
│   └── features.py         # イベント間の特徴量（ioi / gap）
├── annotation.py           # 注釈ノートの解決・優先度チェーン
├── rules/
│   ├── __init__.py
│   ├── engine.py           # 優先度つきルール適用
│   ├── stroke.py           # §04-1
│   ├── palm_mute.py        # §04-2
│   ├── dead_note.py        # §04-3
│   └── legato.py           # §04-4
├── fretboard.py            # Phase 2。Phase 1 は音域による述語のみ
├── render.py               # KS/CC の配置（先行オフセット、リリース KS）
├── validate.py             # 音域・衝突・順序・演奏可能性の検査
├── report.py               # 判定レポート出力
└── rules.default.yaml      # 既定のルール設定
```

`profile/` を分けておくことで、VSOP 対応を後から追加できる。

音高・音価そのものから導ける特徴（`is_power_chord` / `duration_ratio` など）は
`Event` の property に置き、前後のイベントを参照しないと決まらないものだけを
`analysis/features.py` で埋める。

> `analysis/context.py`（`--suggest` の context 推定）は Phase 2 で追加する。

## 5.4 設定ファイル `rules.yaml`

奏法の割り当ては必ずチューニングの反復になる。**コードを触らず調整できる形**に
しないと開発が回らない。

既定値の実体は [`autosguitar/rules.default.yaml`](../autosguitar/rules.default.yaml)。
`--rules my.yaml` で指定したファイルが**再帰的にマージ**されるため、
変えたい項目だけを書けばよい。

```yaml
profile: ksop

annotation_block: [105, 127]
annotations:
  # §03-3.3 参照。キーは MIDI ノート番号
  106: { force: palm_mute }
  ...

# 曲頭に一度だけ書き込む CC。キーは CC 番号
defaults:
  21: 95    # Vib_Speed
  22: 110   # Mute_Time（音源既定 127 より詰めてリフの粒立ちを出す）
  24: 88    # Rel_Shape → 80 以上で自動スライドアウトが有効（§02-2.5）
  25: 108   # Rel_Level
  48: 64    # Magnet

render:
  ks_lead: "tpq/32"          # 全 KS の先行オフセット（§02-2.8）
  ks_velocity: 100
  dedup: false               # 連続同一 KS を抑制するか（§02-2.7 ④）
  ks_track_name: "AutoSG_KS"

analysis:
  chord_tolerance: "tpq/32"          # 和音とみなす発音開始のずれ
  subdivision_candidates: [1, 2, 3, 4, 6]
  grid_tolerance: "tpq/16"

rules:
  stroke:
    rest_reset_beats: 1.0            # この長さ以上の休符でダウンにリセット
    downpick_max_bpm: 170            # 8 分音符換算のダウンピッキング上限
    downpick_max_pitch: 57
    detect_gallop: true
    downpick_requires_context: false # §04-4.1 参照
  palm_mute:
    pitch_strong_below: 57
    pitch_reject_above: 62
    duration_ratio_max: 0.5
    pedal_window_bars: 2
    pedal_min_count: 3
    pedal_min_share: 0.40
    score_threshold: 0.5
    weights:                         # 各特徴のスコア寄与（§04-4.2）
      low_pitch: 0.40
      high_pitch: -1.00
      staccato: 0.20
      pedal_tone: 0.60
      power_chord: 0.20
      full_chord: -0.60
      repeated_pitch: 0.10
  dead_note:
    max_duration_ratio: 0.25
    max_duration: "tpq/8"
    max_velocity: 50
  legato:
    max_interval: 5
    max_gap: "tpq/32"
```

`"tpq/32"` のような文字列は入力 MIDI の分解能から tick 数に解決される。
**固定 tick を書かないこと**。分解能の異なる MIDI で挙動が変わってしまう。

## 5.5 CLI

```
autosguitar INPUT.mid [-o OUTPUT.mid] [options]

  -o, --output FILE         出力 MIDI（既定: <入力>_ks.mid）
  --profile ksop            音源プロファイル（現状 ksop のみ）
  --rules rules.yaml        ルール設定ファイル
  --track N                 処理対象トラック（既定: 実音を最も多く含むトラック）
  --polish 0|1|2            出力の仕上げレベル（§01-1.6。Phase 1 は 0/1 のみ）
  --inline                  KS を実音トラックにマージして単一トラックにする
  --export                  注釈ノート(105–127)を除去する
  --report FILE.csv         判定レポートを出力
  --note-names s1|manual    ノート名の表記系（既定: s1 = Studio One 式）
  --dry-run                 MIDI を書かずレポートのみ
  -q, --quiet               要約を表示しない
```

> `--suggest`（context 注釈の初期案生成）は Phase 2。

終了コード: `0` 正常 / `1` 実行時エラーまたは検証エラー / `2` 引数・設定エラー。

## 5.6 出力仕様

type-1 MIDI。

```
track 0..N-1 : 入力の全トラックをそのまま保持
track N      : [AutoSG_KS]  生成された KS ノート / CC
```

- **入力の全トラックを保持する。** 仕様の初稿は「track 0 / 対象トラック /
  KS トラック」の 3 本構成としていたが、ドラムやベースを含む多トラック MIDI で
  データを失うため、対象外のトラックもそのまま通す
- 実音トラックは**ツールが一切書き換えない**（注釈ノートも保持。`--export` 時のみ除去）
- `AutoSG_KS` は実行のたびにまるごと破棄して再生成する。これにより
  **冪等性が構造的に保証される**（§03-3.5）
- 入力が既に `AutoSG_KS` という名前のトラックを含む場合は破棄して作り直す
- KS トラックの MIDI チャンネルは、対象トラックで最も使われているチャンネルに合わせる
- `--inline` 指定時は KS トラックの内容を対象トラックにマージする。同一 tick では
  `メタ → CC → note_off → KS の note_on → 実音の note_on` の順に並べ替え、
  KS が必ず実音より先に出るようにする

## 5.7 バリデーション

| 検査 | 重大度 | 対応 |
|---|---|---|
| 実音が発音域外（< 35 / > 86） | 警告 | 発音しない旨を報告 |
| 注釈ブロックに未定義のノート | 警告 | 無視する旨を報告 |
| 和音の同時発音数 > 7 | 警告 | 7 弦では鳴らせない |
| 3 音以上の和音が押弦不能 | 警告 | `fretboard.is_playable_chord` で判定 |
| 先行オフセットを確保できない KS | 警告 | 曲頭 tick 0 付近。§02-2.8 のリスクを報告 |
| 生成 KS が発音域に侵入 | エラー | 内部不整合 |
| 生成ノートが KS 域外 | エラー | 内部不整合 |
| KS が対応する実音より後 | エラー | レンダラのバグ検出用 |

エラーが 1 件でもあれば MIDI を書かずに終了する。

> 発音域外ノートの自動オクターブ移動（`--fix-range`）は Phase 2。
> 音を勝手に動かす機能は雛形用途では害が大きいため、後回しにした。

## 5.8 テスト戦略

Sforzando は VST のみで CLI を持たないため、**音での自動回帰テストはできない**。
代わりに以下で担保する。

1. **構造テスト（主軸）** — 生成 MIDI をパースし直し、
   KS の位置・順序・値・CC を assert する。ここは完全に自動化できる
2. **ルール単体テスト** — 合成した Event 列に対する判定結果を assert
3. **冪等性テスト** — 出力を再入力して、KS トラックが増えず内容が一致すること
4. **実データ通しテスト** — `.references/` のメーカー製デモ MIDI で例外なく通ること
   （参照資料がない環境ではスキップ）
5. **ゴールデンファイルテスト**（Phase 2） — 判定レポート CSV を固定して差分検出
6. **聴感確認（手動）** — Studio One で実際に鳴らす。
   必要なら SFZ 互換のオープンソースプレイヤー **sfizz**（`sfizz_render` CLI）で
   オフラインレンダリングし、音の確認を半自動化できる

```
tests/
├── conftest.py         # MidiBuilder フィクスチャ
├── test_profile.py     # §02 の定数と docs の整合
├── test_rules.py       # §04 の各ルール
├── test_annotation.py  # §03 の優先度チェーン
└── test_pipeline.py    # 通し・出力構造・冪等性
```

## 5.9 ロードマップ

### Phase 1（実用最小）— 実装済み

- [x] Parse / Group / Featurize / Annotate / RuleEngine / Render / Validate の骨格
- [x] 注釈レイヤー（§03 全体。優先度チェーン・往復・ロック・手動 KS 尊重）
- [x] 自動ルール: ピッキング方向・パームミュート・デッドノート・レガート（§04-4.9）
- [x] CC 既定値の書き込み（CC24 = 88 で自動スライドアウト有効）
- [x] 判定レポート出力（`Decision.source` による根拠追跡）
- [x] CLI: `--rules` / `--report` / `--inline` / `--export` / `--dry-run`
- [x] テスト 74 件

### Phase 2

- フレットボードモデル（§04-4.8）と、それによる各ルールの述語差し替え
  （`fretboard.py` の `on_low_string` / `bendable` / `reachable_on_one_string` を
  弦割り当ての結果を見る実装に置き換える）
- スライド自動判定 + CC26 / CC27（注釈による強制指定は Phase 1 で実装済み）
- チョーキング自動判定（装飾音畳み込み / ピッチベンド変換）
- `--suggest`（context 推定。`analysis/context.py`）
- `--fix-range`（発音域外ノートのオクターブ移動）
- `--polish 2`（ストラム展開・ヒューマナイズ・ノイズ FX 挿入）
- ゴールデンファイルテスト

### Phase 3

- VSOP プロファイル（velocity → 奏法、強弱を CC11 に移送）
- GUI もしくは DAW 連携
