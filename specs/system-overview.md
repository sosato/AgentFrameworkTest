# 企業統治 GroupChat PoC — システム仕様

## 目的
Microsoft Agent Framework の GroupChatOrchestration を最小構成で動作確認する。
1つのファシリテーターエージェントが議長役となり、企業を代弁する 1つのエージェント (CeoAgent)と外部からの指摘役として 2 つのエージェント（AnalystAgent と CriticAgent）が 企業経営・企業統治に関するテーマで討議し、
その過程と結論をコンソールに表示する。

## スコープ
- **対象領域**：企業経営・企業統治（コーポレートガバナンス）全般
- **討議テーマ**：実行時に引数（`--theme`）として指定する文字列。特定の領域（ESG・財務・人事・戦略等）に限定しない

## ユーザーインプット
- 討議テーマ（文字列）：コマンドライン引数 `--theme` で指定する
  例：「トヨタ自動車のコーポレートガバナンス：取締役会の独立性は十分か？」

## 期待するアウトプット
1. 各エージェントの発言ログ（ラウンド形式）
2. GroupChat 終了後の集約サマリー（最終メッセージ）
3. 総ラウンド数・所要時間の表示

## スコープ外（v3）
- 外部 API 呼び出し（Fabric / EDINET / World Bank）
- ストリーミング表示
- FastAPI / Web UI
- OpenTelemetry トレース
- Human-in-the-loop

## 前提条件（セットアップ）
- エージェント（FacilitatorAgent / CeoAgent / AnalystAgent / CriticAgent）は **事前に Foundry Agent Service へ登録** する
- 登録にはセットアップスクリプトを使用する：`python src/setup_agents.py create`
- 登録済みエージェントの確認：`python src/setup_agents.py list`
- エージェントの削除（再登録時）：`python src/setup_agents.py delete`
- Foundry ポータル上で直接エージェントを作成・編集することも可能

## 技術スタック
- フレームワーク：agent-framework RC（Python）
- オーケストレーション：GroupChatOrchestration（RoundRobin / selection_func）
- モデル：GPT-4.1 via Microsoft Foundry
- エージェント管理：Foundry Agent Service（事前登録）
- ランタイムクライアント：AzureAIClient（use_latest_version=True で Foundry 登録済みエージェントを参照）
- 実行：ローカル CLI（python src/main.py）

### アーキテクチャ
エージェントの定義（instructions・モデル・Foundry IQ 等）は Foundry Agent Service が管理する。
AzureAIClient は use_latest_version=True で登録済みエージェントの最新バージョンを
参照し、Foundry Agent Service 経由で LLM を呼び出す。
ポータルでの構成変更（instructions・Foundry IQ・RAI 設定等）は次回実行時に自動反映される。

### 調査テスト
`tests/test_e2e_foundry.py` で段階的な動作確認が可能：
- Step 1: Foundry 登録確認
- Step 2: 単体エージェント応答テスト
- Step 3: GroupChat 統合テスト（2 ラウンド）
