# Web UI 化 変更仕様書

## 1. 目的・背景

現状はコマンドライン（Python CLI）で動作しているが、より広いユーザーが利用できるよう
React ベースの Web インターフェースを提供する。

主な変更目標：
- ブラウザからディベートテーマ・エージェント・ラウンド数を設定して GroupChat を開始できる
- チャットルーム形式でリアルタイムに各エージェントの発言を表示する
- 議論終了後にサマリーとインサイトを見やすく表示する
- Azure 上に安全に展開し、Entra ID で認証・認可を行う

---

## 2. システムアーキテクチャ概要

```
[ブラウザ (React SPA)]
    │
    │ HTTPS（公開エンドポイント）
    │
[Azure Static Web Apps]   ←─ Azure CDN / Front Door
    │
    │ HTTPS（Private Endpoint 経由、内部通信）
    │
[Azure Container Apps — FastAPI バックエンド]
    │              │
    │              └─ Azure AI Foundry（Agent Service）
    │                   └─ LLM（GPT-4.1）
    │
[Azure Entra ID]  ─── OBO トークン発行
```

### レイヤー構成

| レイヤー | サービス | 公開範囲 |
|----------|----------|----------|
| フロントエンド | Azure Static Web Apps + Azure Front Door | パブリック（インターネット） |
| バックエンド API | Azure Container Apps（FastAPI） | プライベート（VNet 内部のみ） |
| Agent 処理 | Azure AI Foundry Agent Service | プライベート（VNet 内部のみ） |
| 認証 | Azure Entra ID（旧 Azure AD） | パブリック（STS エンドポイント） |
| ストレージ（セッション） | Azure Cosmos DB または Azure Cache for Redis | プライベート |

---

## 3. 認証・認可設計

### 3.1 認証フロー（Entra ID + PKCE + OBO）

```
1. ユーザーがブラウザでアクセス
2. MSAL.js が Entra ID へリダイレクト（Authorization Code + PKCE フロー）
3. 認証成功 → ID トークン + アクセストークン（Scope: api://<backend-app-id>/access_as_user）を取得
4. フロントエンドが API リクエスト時に Authorization: Bearer <access_token> を付与
5. バックエンド（FastAPI）がトークンを検証後、OBO フローで Foundry スコープのトークンに交換
6. 交換済みトークンで Azure AI Foundry Agent Service を呼び出す
```

### 3.2 Entra ID アプリ登録

| 項目 | フロントエンド アプリ | バックエンド アプリ |
|------|-----------------|-----------------|
| 種別 | SPA（Single Page Application） | Web API |
| Redirect URI | `https://<app>.azurestaticapps.net/` | — |
| API アクセス許可 | `api://<backend-app-id>/access_as_user` | Azure AI Foundry の委任スコープ |
| 公開されている API | — | `access_as_user`（委任スコープ） |

### 3.3 バックエンド OBO 処理

```python
# FastAPI ミドルウェア（概略）
async def get_obo_token(user_token: str) -> str:
    """ユーザートークンを Foundry 用 OBO トークンに交換する"""
    # MSAL ConfidentialClientApplication.acquire_token_on_behalf_of()
    ...
```

- OBO トークンはリクエストごとにキャッシュ（`acquire_token_silent` で再利用）
- トークンの有効期限切れは 401 → フロントが自動的に再認証

---

## 4. ネットワーク設計

### 4.1 公開範囲

| コンポーネント | アクセス経路 | 説明 |
|--------------|------------|------|
| Azure Static Web Apps | インターネット → Azure Front Door → SWA | CDN キャッシュ、WAF ルール適用 |
| FastAPI バックエンド（Container Apps） | SWA → VNet Private Endpoint のみ | インターネットから直接アクセス不可 |
| Azure AI Foundry | Container Apps 内部 → VNet Private Endpoint | インターネット非公開 |
| Azure Cosmos DB / Redis | VNet 内部のみ | インターネット非公開 |

### 4.2 VNet 構成

```
VNet: esg-groupchat-vnet (例: 10.0.0.0/16)
  ├── Subnet: frontend-integration  (10.0.1.0/24)  ─ SWA Managed Env / Front Door Origin
  ├── Subnet: backend-apps          (10.0.2.0/24)  ─ Container Apps Environment
  ├── Subnet: private-endpoints     (10.0.3.0/24)  ─ Foundry / Cosmos DB / Redis の Private Endpoint
  └── Subnet: gateway               (10.0.4.0/24)  ─ （将来の VPN GW / ExpressRoute 用）
```

### 4.3 Azure Front Door / WAF

- TLS 1.2 以上を強制
- WAF ポリシー：OWASP 3.2 ルールセット有効化
- バックエンドオリジンは Private Endpoint 経由のみ許可
- カスタムドメイン + Managed TLS 証明書を適用

---

## 5. フロントエンド仕様（React SPA）

### 5.1 技術スタック

| 項目 | 採用技術 |
|------|---------|
| フレームワーク | React 19 + TypeScript |
| ビルドツール | Vite |
| スタイリング | Tailwind CSS |
| 状態管理 | Zustand または React Context |
| 認証ライブラリ | MSAL React（`@azure/msal-react`） |
| HTTP クライアント | Axios |
| リアルタイム通信 | Server-Sent Events（EventSource API） |
| ホスティング | Azure Static Web Apps |

### 5.2 画面構成

```
/                    → ログインページ（未認証時リダイレクト）
/debate              → メインページ（ディベート設定 + チャットルーム）
/debate/:sessionId   → セッション復元（ページリロード対応）
```

### 5.3 メインページ レイアウト

```
┌─────────────────────────────────────────────────────────────┐
│  ESG GroupChat                              [ユーザー名] [▼]  │
├──────────────────┬──────────────────────────────────────────┤
│  ① 設定パネル    │  ③ チャットルーム                         │
│                  │                                          │
│  テーマ入力       │  [FacilitatorAgent] Round 1             │
│  ┌────────────┐  │  「本日のテーマは...」                    │
│  │            │  │                                          │
│  └────────────┘  │  [CeoAgent] Round 2                     │
│                  │  「当社の取り組みとして...」               │
│  ラウンド数       │                                          │
│  [13 ▼]          │  [AnalystAgent] Round 4                 │
│                  │  「評価スコア: 7/10...」                  │
│  ② エージェント  │                                          │
│  選択ペーン       │  ・・・（ストリーミング表示）              │
│                  │                                          │
│  ☑ FacilitatorAgent│                                       │
│  ☑ CeoAgent     │  ④ 結果パネル（議論完了後に表示）          │
│  ☑ AnalystAgent  │  ┌──────────────┬─────────────────────┐  │
│  ☑ CriticAgent  │  │ 議論サマリー  │ インサイト           │  │
│                  │  └──────────────┴─────────────────────┘  │
│  [▶ 開始]        │                                          │
└──────────────────┴──────────────────────────────────────────┘
```

---

## 6. UI/UX 詳細仕様

### 6.1 ① 設定パネル

| 項目 | コンポーネント | バリデーション |
|------|--------------|--------------|
| 討議テーマ | `<textarea>` (最大 500 字) | 必須、最低 5 字 |
| ラウンド数 | `<select>` (5 / 7 / 9 / 11 / 13 / 15) | 必須、min 5 |
| 開始ボタン | `<button>` | テーマ・エージェント選択済み かつ 非実行中のみ有効 |
| 停止ボタン | `<button>` | 実行中のみ有効（セッション中断） |

テーマ入力欄には例示プレースホルダーを表示する：
> 例：「トヨタ自動車のコーポレートガバナンス：取締役会の独立性は十分か？」

### 6.2 ② エージェント選択ペーン

- 利用可能なエージェント一覧を API から取得してチェックボックスで表示
- `FacilitatorAgent` は常に必須（チェック解除不可・グレーアウト）
- 討論エージェント（CeoAgent / AnalystAgent / CriticAgent）は最低 2 つ選択必須
- 各エージェントのツールチップ（ホバー時）でエージェントの役割説明を表示
- 将来的なカスタムエージェント追加を考慮した拡張可能な設計

### 6.3 ③ チャットルーム

- 各発言は「エージェント名バッジ」＋「ラウンド番号」＋「発言テキスト」で表示
- エージェントごとにバッジカラーを固定：
  - FacilitatorAgent: 紺色 (`#1E3A5F`)
  - CeoAgent: 緑色 (`#1B5E20`)
  - AnalystAgent: 青色 (`#0D47A1`)
  - CriticAgent: 赤色 (`#B71C1C`)
- SSE ストリーミングによりテキストを文字単位でリアルタイム表示（タイピングアニメーション効果）
- 新しいメッセージが追加されると自動スクロール（ユーザーが手動スクロールアップ中は自動スクロール停止）
- AnalystAgent / CriticAgent の発言内にスコア（`X/10`）が含まれる場合はバッジで強調表示
- 「コピー」ボタンで全チャットログをクリップボードにコピー可能

### 6.4 ④ 結果パネル（議論完了後）

議論が完了すると、チャットルームの下部に結果パネルがアニメーション付きで展開される。

**議論サマリー タブ**
- FacilitatorAgent の最終発言（ラウンド最終）を抽出して表示
- Markdown レンダリング対応（見出し・箇条書き等）

**インサイト タブ**
- AnalystAgent と CriticAgent のスコアの変化（初期スコア → 最終スコア）をグラフ表示
- 各エージェントが言及した主要キーワードをタグクラウドで表示
- 「賛成論点」「反対論点」「共通見解」「残課題」を構造化して表示
  （FacilitatorAgent の最終発言から LLM で抽出）

結果パネルには「PDFエクスポート」ボタンを設け、議論ログ＋サマリー＋インサイトを
1 ページの PDF としてダウンロードできるようにする。

---

## 7. バックエンド API 仕様（FastAPI）

### 7.1 技術スタック

| 項目 | 採用技術 |
|------|---------|
| フレームワーク | FastAPI |
| 認証ミドルウェア | `fastapi-azure-auth` または `python-jose` |
| OBO フロー | MSAL Python (`msal`) |
| ASGI サーバー | Uvicorn |
| コンテナ化 | Docker → Azure Container Apps |
| ロギング | Azure Application Insights（OpenTelemetry） |

### 7.2 エンドポイント一覧

| メソッド | パス | 説明 | 認証 |
|---------|------|------|------|
| GET | `/agents` | 利用可能なエージェント一覧を返す | Bearer |
| POST | `/sessions` | 新規ディベートセッションを作成する | Bearer |
| GET | `/sessions/{session_id}/stream` | SSE でエージェント発言をストリーミング | Bearer |
| GET | `/sessions/{session_id}` | セッション状態・結果を取得する | Bearer |
| DELETE | `/sessions/{session_id}` | セッションを中断・削除する | Bearer |
| GET | `/health` | ヘルスチェック | なし |

### 7.3 リクエスト / レスポンス スキーマ

#### POST `/sessions`

```json
// Request
{
  "topic": "トヨタ自動車のコーポレートガバナンス：取締役会の独立性は十分か？",
  "max_rounds": 13,
  "agents": ["FacilitatorAgent", "CeoAgent", "AnalystAgent", "CriticAgent"]
}

// Response 201 Created
{
  "session_id": "sess_abc123",
  "status": "created",
  "created_at": "2026-03-17T09:00:00Z"
}
```

#### GET `/sessions/{session_id}/stream`（SSE）

```
Content-Type: text/event-stream

event: chunk
data: {"round": 1, "agent": "FacilitatorAgent", "text": "本日の"}

event: chunk
data: {"round": 1, "agent": "FacilitatorAgent", "text": "テーマは"}

event: round_complete
data: {"round": 1, "agent": "FacilitatorAgent", "full_text": "本日のテーマは..."}

event: session_complete
data: {"session_id": "sess_abc123", "total_rounds": 13, "duration_sec": 245}

event: error
data: {"code": "AGENT_TIMEOUT", "message": "エージェントの応答がタイムアウトしました"}
```

#### GET `/sessions/{session_id}`

```json
// Response 200 OK
{
  "session_id": "sess_abc123",
  "status": "completed",  // "created" | "running" | "completed" | "aborted" | "error"
  "topic": "トヨタ自動車のコーポレートガバナンス...",
  "max_rounds": 13,
  "agents": ["FacilitatorAgent", "CeoAgent", "AnalystAgent", "CriticAgent"],
  "messages": [
    {
      "round": 1,
      "agent": "FacilitatorAgent",
      "text": "本日のテーマは...",
      "timestamp": "2026-03-17T09:00:05Z"
    }
  ],
  "result": {
    "summary": "...",    // FacilitatorAgent の最終発言
    "scores": {
      "AnalystAgent":  {"initial": 7, "final": 8},
      "CriticAgent":   {"initial": 4, "final": 5}
    }
  }
}
```

### 7.4 エラーコード

| コード | HTTP Status | 説明 |
|--------|------------|------|
| `UNAUTHORIZED` | 401 | トークン無効・期限切れ |
| `SESSION_NOT_FOUND` | 404 | セッション ID が存在しない |
| `SESSION_ALREADY_RUNNING` | 409 | 同一ユーザーのセッションが実行中 |
| `AGENT_TIMEOUT` | 504 | エージェント応答タイムアウト |
| `FOUNDRY_ERROR` | 502 | Foundry Agent Service エラー |
| `VALIDATION_ERROR` | 422 | リクエストパラメータ不正 |

---

## 8. セッション管理

- ユーザーごとに同時実行セッションは最大 1 件（新規開始時に既存セッションを確認）
- セッション結果は Azure Cosmos DB（または Azure Cache for Redis）に保存し、ページリロード後も復元可能
- セッションの保存期間：完了後 7 日間（TTL 設定）
- セッション ID は URL に含まれ、共有・ブックマーク可能（認証ユーザーのみアクセス可）

---

## 9. リアルタイム通信設計

### 9.1 方式の選択

| 方式 | 採用 | 理由 |
|------|------|------|
| Server-Sent Events (SSE) | ✅ 採用 | サーバーからクライアントへの一方向ストリームに最適。実装が単純で Azure Front Door でも動作可能 |
| WebSocket | ❌ 不採用 | 双方向通信が不要。Azure Static Web Apps の SSE サポートと相性が良い |
| Long Polling | ❌ 不採用 | オーバーヘッドが大きく体験が劣る |

### 9.2 SSE 接続管理

- SSE 接続は Bearer トークンをクエリパラメータ（`?token=...`）またはカスタムヘッダーで渡す
  （EventSource API は Authorization ヘッダー非対応のため）
- クエリパラメータ使用時はトークンの有効期間を短く設定（5 分）し、URL ログへの露出を最小化
- 接続断時は指数バックオフでリコネクト（最大 5 回）
- セッション完了後は SSE 接続を自動クローズ

---

## 10. Azure デプロイ構成

### 10.1 必要な Azure リソース

| リソース | SKU / 構成 | 用途 |
|---------|-----------|------|
| Azure Static Web Apps | Standard | フロントエンド SPA ホスティング |
| Azure Front Door + WAF | Standard | CDN、WAF、カスタムドメイン |
| Azure Container Apps | Consumption プラン（VNet 統合） | FastAPI バックエンド |
| Azure Container Registry | Basic | Docker イメージ管理 |
| Azure AI Foundry | 既存 | Agent Service / LLM |
| Azure Cosmos DB（Serverless） | または Redis Cache Basic | セッションストレージ |
| Azure Key Vault | Standard | シークレット管理（OBO クライアントシークレット等） |
| Azure Application Insights | — | テレメトリ・ログ |
| Azure Virtual Network | — | バックエンド Private Endpoint |

### 10.2 環境変数（Container Apps）

| 変数名 | 説明 | 取得元 |
|--------|------|--------|
| `ENTRA_TENANT_ID` | Entra ID テナント ID | Key Vault |
| `ENTRA_CLIENT_ID` | バックエンドアプリの Client ID | Key Vault |
| `ENTRA_CLIENT_SECRET` | バックエンドアプリの Client Secret | Key Vault |
| `FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry エンドポイント | Key Vault |
| `AZURE_DEPLOYMENT_NAME` | LLM デプロイ名 | 環境変数 |
| `COSMOS_DB_ENDPOINT` | Cosmos DB エンドポイント | 環境変数 |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights 接続文字列 | Key Vault |

### 10.3 IaC（Infrastructure as Code）

- Bicep または Terraform で全リソースをコード管理
- GitHub Actions による CI/CD パイプライン：
  - フロントエンド：`main` ブランチへのプッシュ → SWA 自動デプロイ
  - バックエンド：Docker ビルド → ACR プッシュ → Container Apps 更新

---

## 11. セキュリティ考慮事項

| 項目 | 対策 |
|------|------|
| 認証 | Entra ID PKCE フロー（SPA）。クライアントシークレットはフロントエンドに保持しない |
| OBO トークン | バックエンドのみで保持。Key Vault から取得したシークレットで処理 |
| HTTPS 強制 | Front Door → Container Apps 間も HTTPS（Private Link）。HTTP → HTTPS リダイレクト設定 |
| CORS | バックエンドの CORS 許可オリジンは SWA の URL のみに制限 |
| WAF | OWASP 3.2 ルールセット + カスタムルール（レート制限: 100 req/min/IP） |
| シークレット管理 | コード・環境変数に直接記載しない。Key Vault 参照を使用 |
| コンテナセキュリティ | Container Apps のマネージド ID で Key Vault / ACR にアクセス |
| SSE トークン | クエリパラメータのトークンは短命（有効期間 5 分）で専用スコープ |
| ログ | Application Insights でアクセスログ・エラーログを収集。個人情報（ユーザー ID）はハッシュ化 |
| 入力検証 | テーマ文字列のサニタイズ（XSS 対策）。ラウンド数の境界値チェック |

---

## 12. 非機能要件

| 項目 | 要件 |
|------|------|
| 可用性 | 99.9%（SLA: Static Web Apps + Front Door） |
| レスポンス（API） | セッション作成 < 2 秒 |
| スループット | 同時セッション数: 初期は最大 10（Container Apps のスケールアウトで調整） |
| SSE タイムアウト | 1 セッションあたり最大 30 分 |
| エージェントタイムアウト | 各ターン 120 秒（既存設定を継承） |
| ブラウザ対応 | Chrome / Edge 最新版、Firefox 最新版、Safari 最新版 |
| アクセシビリティ | WCAG 2.1 AA 準拠を目標 |
| ログ保持期間 | Application Insights: 90 日 |

---

## 13. 将来の拡張考慮事項（スコープ外 v1）

- カスタムエージェントの追加 UI（Foundry ポータル連携）
- ディベートテーマのテンプレート機能
- 複数ユーザーによる同一セッション閲覧（観戦モード）
- Human-in-the-loop（ユーザーが途中で介入してエージェントに指示できる）
- 外部 API 連携（EDINET / World Bank データ自動取得）
- OpenTelemetry による詳細トレーシング
- 多言語対応（英語 UI）

---

## 14. スコープ外（v1）

- カスタムエージェントの作成・編集機能
- ユーザー管理・ロール管理（Entra ID グループベースの認可は v2 以降）
- モバイルアプリ（iOS / Android）
- オンプレミス / ハイブリッド構成
- リアルタイム音声読み上げ（TTS）
