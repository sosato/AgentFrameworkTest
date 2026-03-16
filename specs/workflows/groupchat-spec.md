# GroupChat ワークフロー仕様（v3 最小版）

## 前提条件
- AnalystAgent / CriticAgent が Foundry Agent Service に **事前登録済み** であること
- 未登録の場合は `python src/setup_agents.py create` を実行する

## 参加エージェント
1. AnalystAgent（アナリスト）
2. CriticAgent（クリティック）

## 討議ルール
- オーケストレーター：RoundRobin（交互発言）
- 最大ラウンド数：6
- 終了条件：max_rounds に到達した時点で自動終了

## フロー
Round 1: AnalystAgent → テーマ分析・初期評価スコア提示
Round 2: CriticAgent → 反論・カウンタースコア提示
Round 3: AnalystAgent → 反論への応答・根拠補強
Round 4: CriticAgent → 追加指摘 or 部分的合意
Round 5: AnalystAgent → 議論の収束・共通見解の提示
Round 6: CriticAgent → 最終コメント・改善提案

## 終了後の処理
- 全発言ログを収集
- 最後のメッセージを「最終結論」として表示
- AnalystAgent と CriticAgent の初期・最終スコアを抽出して比較表示

## 非機能要件
- API タイムアウト：各ターン 30 秒
- エラー時：エラーメッセージを表示して処理を中断（リトライなし）
