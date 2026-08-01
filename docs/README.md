# AutoSGuitar 仕様ドキュメント

Sforzando 音源 **Standard Guitar** 向けに、入力 MIDI へルールベースでキースイッチ（KS）と
コントロールチェンジ（CC）を自動付加するツールの仕様書。

## 目的

DAW で手打ちする際の**雛形（叩き台）となる MIDI を自動生成**する。
完全自動での完成品生成は目標としない。ツールが 7〜8 割を埋め、
残りを注釈レイヤー経由でユーザーが指示して往復する運用を前提とする。

## ドキュメント構成

| ファイル | 内容 |
|---|---|
| [01-overview.md](01-overview.md) | 背景・スコープ・実現可能性の判断根拠 |
| [02-sound-source-spec.md](02-sound-source-spec.md) | 音源リファレンス（KSマップ / CC / 配置規則）。**実装が参照する定数の出所** |
| [03-annotation-layer.md](03-annotation-layer.md) | 注釈レイヤー仕様・往復ワークフロー |
| [04-articulation-rules.md](04-articulation-rules.md) | キースイッチ付加ルール（ギター奏法の知識ベース） |
| [05-architecture.md](05-architecture.md) | アーキテクチャ・データモデル・CLI・ロードマップ |

## 実装状況

**Phase 1 実装済み。** 使い方は [ルート README](../README.md) を参照。
ロードマップは [05-architecture.md §5.9](05-architecture.md)。

## 確定事項サマリ

- 対象パッチは **KSOP**（`01-Standard Guitar KSOP`）。VSOP は将来対応
- 出力は type-1 MIDI。生成 KS/CC は専用トラック `AutoSG_KS` に分離し、毎回まるごと再生成する
- 注釈は**発音域外ノート（MIDI 105–127）**で与える。Studio One でノート単位の
  MIDI チャンネル編集ができないため、チャンネル方式は採用しない
- リード/バッキングの区別は自動推定せず、注釈で与える
- Phase 1 の自動判定範囲は ピッキング方向 / パームミュート / デッドノート / レガート の 4 つ

## 参照資料

すべて `.references/` 配下（リポジトリには含めない）。

- `UI_Standard_Guitar/見てね♡/Standard_Guitar_KSMap.txt` — KS マップ
- `UI_Standard_Guitar/見てね♡/説明および注意事項.txt` — CC 仕様・注意点（Shift-JIS）
- `UI_Standard_Guitar/Programs/**/*.sfz` — 音域・KS 宣言域の一次情報
- `Standard Guitar_Manual/Sample_MIDI_Files/` — メーカー製サンプル MIDI（配置規則の裏取りに使用）
