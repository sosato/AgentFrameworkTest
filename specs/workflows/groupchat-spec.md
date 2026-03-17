# GroupChat ワークフロー仕様（v5 ファシリテーター動的選択形式）

## 前提条件
- FacilitatorAgent / CeoAgent / AnalystAgent / CriticAgent が Foundry Agent Service に **事前登録済み** であること
- 未登録の場合は `python src/setup_agents.py create` を実行する

## 参加エージェント
1. FacilitatorAgent（ファシリテーター／議長）
2. CeoAgent（CEO／企業代弁者）
3. AnalystAgent（アナリスト）
4. CriticAgent（クリティック）

## 討議ルール
- オーケストレーター：selection_func（ファシリテーター動的制御）
- デフォルト最大ラウンド数：13
- 最小ラウンド数：5
- 終了条件：max_rounds に到達した時点で自動終了
- 選択ロジック（動的発言者割り当て）：
  - Round 1（偶数 idx=0）：FacilitatorAgent（討議開始・テーマ紹介 + 最初の発言者指定）
  - Round 奇数（idx=1,3,5,...）：討論者（ファシリテーターのディレクティブで動的に選択）
  - Round 偶数・中間（idx=2,4,6,...）：FacilitatorAgent（コメント + 次の発言者指定）
  - Round 最終（偶数・idx=max_rounds-1）：FacilitatorAgent（討議終了・サマリー）

## 動的発言者選択の仕組み
- ファシリテーターは各発言の末尾に `【次の発言者: XXXAgent】` ディレクティブを含める
- 選択関数はこのディレクティブを解析して次の討論者を決定する
- ディレクティブが見つからない場合は `(round_idx - 1) // 2 % 3` のラウンドロビンにフォールバックする

## フロー（デフォルト 13 ラウンド）
Round 1 (idx=0):  FacilitatorAgent → 討議の開始宣言・テーマと参加者の紹介【次の発言者: CeoAgent】
Round 2 (idx=1):  CeoAgent         → 企業の ESG 取り組みと基本姿勢の表明
Round 3 (idx=2):  FacilitatorAgent → CEO の発言を受けたコメント【次の発言者: AnalystAgent】
Round 4 (idx=3):  AnalystAgent     → テーマ分析・初期評価スコア提示
Round 5 (idx=4):  FacilitatorAgent → アナリストの発言を受けたコメント【次の発言者: CriticAgent】
Round 6 (idx=5):  CriticAgent      → 反論・カウンタースコア提示
Round 7 (idx=6):  FacilitatorAgent → クリティックの発言を受けたコメント【次の発言者: CeoAgent】
Round 8 (idx=7):  CeoAgent         → 指摘への応答・追加情報の提示
Round 9 (idx=8):  FacilitatorAgent → CEO の応答を受けたコメント【次の発言者: AnalystAgent】
Round 10 (idx=9): AnalystAgent     → 反論への応答・根拠補強
Round 11 (idx=10):FacilitatorAgent → アナリストの発言を受けたコメント【次の発言者: CriticAgent】
Round 12 (idx=11):CriticAgent      → 追加指摘 or 部分的合意
Round 13 (idx=12):FacilitatorAgent → 討議のまとめ・共通見解の整理・結論提示

## 終了後の処理
- 全発言ログを収集
- FacilitatorAgent の最終発言を「最終結論」として表示
- AnalystAgent と CriticAgent の初期・最終スコアを抽出して比較表示

## 非機能要件
- API タイムアウト：各ターン 30 秒
- エラー時：エラーメッセージを表示して処理を中断（リトライなし）
