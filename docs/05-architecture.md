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

## 5.3 モジュール構成（案）

```
autosguitar/
├── __init__.py
├── cli.py                  # エントリポイント
├── model.py                # Note / Event / Decision / Articulation
├── profile/
│   ├── __init__.py
│   └── ksop.py             # §02 の定数テーブル（KS マップ / CC / 音域）
├── io/
│   ├── reader.py           # mido → Note[] + テンポマップ
│   └── writer.py           # Decision[] → MidiFile
├── analysis/
│   ├── grid.py             # 拍・分割推定、スナップ
│   ├── grouping.py         # 同時発音の Event 化
│   ├── features.py         # 特徴量算出
│   └── context.py          # --suggest の context 推定
├── annotation.py           # 注釈ノートの解決・優先度チェーン
├── rules/
│   ├── engine.py           # 優先度つきルール適用
│   ├── stroke.py           # §04-1
│   ├── palm_mute.py        # §04-2
│   ├── dead_note.py        # §04-3
│   └── legato.py           # §04-4
├── fretboard.py            # Phase 2。Phase 1 は述語のスタブのみ
├── render.py               # KS/CC の配置（先行オフセット、リリース KS）
├── validate.py             # 音域・衝突・順序検査
└── report.py               # 判定レポート出力
```

`profile/` を分けておくことで、VSOP 対応を後から追加できる。

## 5.4 設定ファイル `rules.yaml`

奏法の割り当ては必ずチューニングの反復になる。**コードを触らず調整できる形**に
しないと開発が回らない。

```yaml
profile: ksop

annotation_block: [105, 127]
annotations:
  # §03-3.3 参照
  ...

defaults:
  cc21: 95          # Vib_Speed
  cc22: 110         # Mute_Time（既定 127 より詰めてリフの粒立ちを出す）
  cc24: 88          # Rel_Shape → 自動スライドアウト有効（§02-2.5）
  cc25: 108         # Rel_Level
  cc48: 64          # Magnet

render:
  ks_lead: "tpq/32"     # 全 KS の先行オフセット（§02-2.8）
  ks_velocity: 100
  dedup: false          # 連続同一 KS を抑制するか（§02-2.7 ④）

rules:
  stroke:
    rest_reset_beats: 1.0         # この長さ以上の休符でダウンにリセット
    downpick_max_bpm: 170         # 8分音符のダウンピッキング上限
    downpick_max_pitch: 57
  palm_mute:
    pitch_strong_below: 57
    pitch_reject_above: 62
    duration_ratio_max: 0.5
    pedal_window_bars: 2
    pedal_min_count: 3
    pedal_min_share: 0.40
    score_threshold: 0.5
  dead_note:
    max_duration_ratio: 0.25
    max_velocity: 50
  legato:
    max_interval: 5
    max_gap: "tpq/32"
```

## 5.5 CLI

```
autosguitar INPUT.mid -o OUTPUT.mid [options]

  --profile ksop            音源プロファイル（現状 ksop のみ）
  --rules rules.yaml        ルール設定ファイル
  --track N                 処理対象トラック（既定: 実音を含むトラックを自動選択）
  --polish 0|1|2            出力の仕上げレベル（§01-1.6）
  --suggest                 context 注釈の初期案を書き込む（§03-3.7）
  --inline                  KS を実音トラックにマージして単一トラックにする
  --export                  注釈ノート(105–127)を除去する
  --report FILE.csv         判定レポートを出力
  --note-names s1|manual    ログのノート名表記系（既定: s1 = Studio One 式）
  --dry-run                 MIDI を書かずレポートのみ
```

## 5.6 出力仕様

type-1 MIDI。

```
track 0: テンポ / 拍子（入力を保持）
track 1: [Guitar]     入力ノート＋注釈ノートをそのまま保持
track 2: [AutoSG_KS]  生成された KS ノート / CC
```

- `AutoSG_KS` は実行のたびにまるごと破棄して再生成する。これにより
  **冪等性が構造的に保証される**（§03-3.5）
- 入力が既に `AutoSG_KS` を含む場合は読み飛ばして破棄する
- `--inline` 指定時は track 2 の内容を track 1 にマージし、KS が実音より
  先行するようイベント順序を整える

## 5.7 バリデーション

| 検査 | 対応 |
|---|---|
| 実音が発音域外（< 35 / > 86） | 警告。`--fix-range` でオクターブ移動（既定は無効） |
| 実音が注釈ブロックと衝突 | エラー |
| 生成 KS が発音域に侵入 | エラー（内部不整合） |
| 同一 tick で KS が実音より後 | エラー（レンダラのバグ検出用） |
| 和音の同時発音数 > 7 | 警告（7 弦では鳴らせない） |
| context 注釈の重複 | 警告（§03-3.4 の解決規則を適用） |

## 5.8 テスト戦略

Sforzando は VST のみで CLI を持たないため、**音での自動回帰テストはできない**。
代わりに以下で担保する。

1. **構造テスト（主軸）** — 生成 MIDI をパースし直し、
   KS の位置・順序・値・CC を assert する。ここは完全に自動化できる
2. **ルール単体テスト** — 合成した Event 列に対する判定結果を assert
3. **ゴールデンファイルテスト** — 代表的な入力に対する判定レポート（CSV）を
   固定し、差分を検出する
4. **聴感確認（手動）** — Studio One で実際に鳴らす。
   必要なら SFZ 互換のオープンソースプレイヤー **sfizz**（`sfizz_render` CLI）で
   オフラインレンダリングし、音の確認を半自動化できる

## 5.9 ロードマップ

### Phase 1（実用最小）

- Parse / Group / Featurize / Render / Validate の骨格
- 注釈レイヤー（§03 全体）
- 自動ルール: ピッキング方向・パームミュート・デッドノート・レガート（§04-4.9）
- CC 既定値の書き込み（特に CC24 = 自動スライドアウト）
- 判定レポート出力
- CLI: `--rules` / `--report` / `--inline` / `--export` / `--dry-run`

### Phase 2

- フレットボードモデル（§04-4.8）と、それによる各ルールの述語差し替え
- スライド自動判定 + CC26 / CC27
- チョーキング自動判定（装飾音畳み込み / ピッチベンド変換）
- `--suggest`（context 推定）
- `--polish 2`（ストラム展開・ヒューマナイズ・ノイズ FX 挿入）

### Phase 3

- VSOP プロファイル（velocity → 奏法、強弱を CC11 に移送）
- GUI もしくは DAW 連携
