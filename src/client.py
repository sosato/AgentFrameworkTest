"""AzureAIClient ファクトリ — Foundry Agent Service 経由でエージェントを実行する。"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from agent_framework import BaseChatClient

load_dotenv()


def get_chat_client(agent_name: str) -> BaseChatClient:
    """エージェント名に対応する AzureAIClient を返す。

    Foundry Agent Service に事前登録されたエージェントの最新バージョンを参照し、
    Foundry IQ やポータル側の設定（RAI 等）をそのまま利用する。

    Args:
        agent_name: Foundry に登録済みのエージェント名
    """
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if endpoint:
        from azure.identity import DefaultAzureCredential

        from agent_framework_azure_ai import AzureAIClient

        deployment = os.getenv("AZURE_DEPLOYMENT_NAME")
        if not deployment:
            raise ValueError(
                "AZURE_DEPLOYMENT_NAME を .env に設定してください"
            )

        return AzureAIClient(
            project_endpoint=endpoint,
            model_deployment_name=deployment,
            credential=DefaultAzureCredential(),
            agent_name=agent_name,
            use_latest_version=True,
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "FOUNDRY_PROJECT_ENDPOINT または OPENAI_API_KEY を .env に設定してください"
        )

    from agent_framework.openai import OpenAIChatClient

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    return OpenAIChatClient(api_key=api_key, model=model)
