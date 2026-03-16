"""AzureAIClient + GroupChatOrchestration の動作調査スクリプト。

段階的にテストを実行し、問題箇所を特定する。

使い方:
    python tests/test_e2e_foundry.py              -- 全テスト実行
    python tests/test_e2e_foundry.py --step 1     -- ステップ 1 のみ
    python tests/test_e2e_foundry.py --step 2     -- ステップ 2 のみ
    python tests/test_e2e_foundry.py --step 3     -- ステップ 3 のみ
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# src/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# agent_framework_azure_ai のログを表示して警告を可視化
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# AzureAIClient の内部ログを DEBUG にして詳細を取得
logging.getLogger("agent_framework_azure_ai").setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────
# Step 1: Foundry 登録の確認
# ─────────────────────────────────────────────────────────
def step1_verify_foundry_agents() -> bool:
    """Foundry に AnalystAgent / CriticAgent が登録済みか確認する。"""
    print("\n" + "=" * 60)
    print("Step 1: Foundry エージェント登録の確認")
    print("=" * 60)

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("✗ FOUNDRY_PROJECT_ENDPOINT が設定されていません")
        return False

    client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )

    required = {"FacilitatorAgent", "CeoAgent", "AnalystAgent", "CriticAgent"}
    found = set()

    print(f"\n登録済みエージェント:")
    for agent in client.agents.list():
        latest = agent.versions.latest
        defn = latest.definition
        print(f"  ✓ {agent.name}")
        print(f"    version : {latest.version}")
        print(f"    model   : {defn.model}")
        print(f"    instruct: {(defn.instructions or '')[:60]}...")
        found.add(agent.name)

    missing = required - found
    if missing:
        print(f"\n✗ 未登録: {missing}")
        print("  → python src/setup_agents.py create を実行してください")
        return False

    print(f"\n✓ 両エージェントが登録済みです")
    return True


# ─────────────────────────────────────────────────────────
# Step 2: 単体エージェント応答テスト
# ─────────────────────────────────────────────────────────
async def step2_single_agent_test() -> bool:
    """各エージェントを個別に呼び出し、応答が返るか確認する。"""
    print("\n" + "=" * 60)
    print("Step 2: 単体エージェント応答テスト（AzureAIClient）")
    print("=" * 60)

    from agents.analyst_agent import create_analyst_agent
    from agents.ceo_agent import create_ceo_agent
    from agents.critic_agent import create_critic_agent
    from agents.facilitator_agent import create_facilitator_agent

    test_topic = "トヨタ自動車の ESG 評価について簡潔に一行で述べてください。"
    ok = True

    for name, create_fn in [
        ("FacilitatorAgent", create_facilitator_agent),
        ("CeoAgent", create_ceo_agent),
        ("AnalystAgent", create_analyst_agent),
        ("CriticAgent", create_critic_agent),
    ]:
        print(f"\n--- {name} をテスト中 ---")
        try:
            agent = create_fn()
            start = time.perf_counter()
            response = await asyncio.wait_for(
                agent.run(test_topic),
                timeout=30,
            )
            elapsed = time.perf_counter() - start

            # AgentResponse はイテラブルではない場合がある
            text = None
            if hasattr(response, "text"):
                text = response.text
            elif hasattr(response, "output"):
                text = str(response.output)
            elif hasattr(response, "value"):
                text = str(response.value)
            else:
                # dir で属性を確認
                text = f"(応答型: {type(response).__name__}, attrs: {[a for a in dir(response) if not a.startswith('_')]})"

            print(f"  ✓ 応答取得 ({elapsed:.1f}秒)")
            print(f"    {str(text)[:200]}")

        except TimeoutError:
            print(f"  ✗ タイムアウト（30秒）")
            ok = False
        except Exception as exc:
            print(f"  ✗ エラー: {type(exc).__name__}: {exc}")
            ok = False

    return ok


# ─────────────────────────────────────────────────────────
# Step 3: GroupChat 統合テスト（2 ラウンド）
# ─────────────────────────────────────────────────────────
async def step3_groupchat_mini() -> bool:
    """最小構成（2 ラウンド）で GroupChat を実行する。"""
    print("\n" + "=" * 60)
    print("Step 3: GroupChat 統合テスト（2 ラウンド, selection_func）")
    print("=" * 60)

    from workflows.groupchat import run_groupchat

    topic = "トヨタ自動車の ESG 評価：環境への取り組みは十分か？"
    max_rounds = 2

    print(f"\nテーマ: {topic}")
    print(f"ラウンド数: {max_rounds}")

    try:
        result = await asyncio.wait_for(
            run_groupchat(topic=topic, max_rounds=max_rounds),
            timeout=120,
        )

        print(f"\n✓ GroupChat 完了")
        print(f"  ラウンド数: {result.total_rounds}")
        print(f"  所要時間  : {result.elapsed_seconds}秒")
        for msg in result.messages:
            print(f"  [R{msg.round_num}] {msg.agent_name}: {msg.content[:80]}...")

        return True

    except TimeoutError:
        print(f"\n✗ GroupChat がタイムアウトしました（120秒）")
        return False
    except Exception as exc:
        print(f"\n✗ GroupChat エラー: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────
async def run_all(step: int | None = None) -> None:
    """指定ステップまたは全ステップを実行する。"""
    results: dict[str, bool] = {}

    if step is None or step == 1:
        results["Step 1: Foundry 登録確認"] = step1_verify_foundry_agents()
        if not results["Step 1: Foundry 登録確認"] and step is None:
            print("\n⚠ Step 1 失敗のため以降のテストをスキップします")
            _print_summary(results)
            return

    if step is None or step == 2:
        results["Step 2: 単体エージェント"] = await step2_single_agent_test()
        if not results.get("Step 2: 単体エージェント", True) and step is None:
            print("\n⚠ Step 2 失敗のため Step 3 をスキップします")
            _print_summary(results)
            return

    if step is None or step == 3:
        results["Step 3: GroupChat"] = await step3_groupchat_mini()

    _print_summary(results)


def _print_summary(results: dict[str, bool]) -> None:
    """テスト結果サマリーを表示する。"""
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    for name, ok in results.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}  {name}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AzureAIClient + GroupChat 動作調査",
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="実行するステップ（省略時は全ステップ）",
    )
    args = parser.parse_args()
    asyncio.run(run_all(step=args.step))


if __name__ == "__main__":
    main()
