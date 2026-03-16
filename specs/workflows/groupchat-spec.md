# GroupChat ワークフロー仕様（v4 ファシリテーター討論形式）

## 前提条件
- FacilitatorAgent / CeoAgent / AnalystAgent / CriticAgent が Foundry Agent Service に **事前登録済み** であること
- 未登録の場合は `python src/setup_agents.py create` を実行する

## 参加エージェント
1. FacilitatorAgent（ファシリテーター／議長）
2. CeoAgent（CEO／企業代弁者）
3. AnalystAgent（アナリスト）
4. CriticAgent（クリティック）

## 討議ルール
- オーケストレーター：selection_func（ファシリテーター制御）
- 最大ラウンド数：9
- 終了条件：max_rounds に到達した時点で自動終了
- 選択ロジック：
  - Round 1：FacilitatorAgent（討議開始・テーマ紹介）
  - Rounds 2〜8：CeoAgent → AnalystAgent → CriticAgent の順で循環
  - Round 9：FacilitatorAgent（討議終了・サマリー）

## フロー（デフォルト 9 ラウンド）
Round 1: FacilitatorAgent → 討議の開始宣言・テーマと参加者の紹介
Round 2: CeoAgent → 企業の ESG 取り組みと基本姿勢の表明
Round 3: AnalystAgent → テーマ分析・初期評価スコア提示
Round 4: CriticAgent → 反論・カウンタースコア提示
Round 5: CeoAgent → 指摘への応答・追加情報の提示
Round 6: AnalystAgent → 反論への応答・根拠補強
Round 7: CriticAgent → 追加指摘 or 部分的合意
Round 8: CeoAgent → 企業としての改善意向・最終見解
Round 9: FacilitatorAgent → 討議のまとめ・共通見解の整理・結論提示

## 終了後の処理
- 全発言ログを収集
- FacilitatorAgent の最終発言を「最終結論」として表示
- AnalystAgent と CriticAgent の初期・最終スコアを抽出して比較表示

## 非機能要件
- API タイムアウト：各ターン 30 秒
- エラー時：エラーメッセージを表示して処理を中断（リトライなし）
