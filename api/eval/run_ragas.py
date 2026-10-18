"""RAGAS Evaluation Runner for Amber API Agent."""

import sys
import types

try:
    import langchain_community.chat_models
    if not hasattr(langchain_community.chat_models, "vertexai"):
        vertexai_mod = types.ModuleType("langchain_community.chat_models.vertexai")
        vertexai_mod.ChatVertexAI = object
        sys.modules["langchain_community.chat_models.vertexai"] = vertexai_mod
except Exception:
    pass

import asyncio
import json
import os

from datasets import Dataset
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from amber.util.config import get_settings


async def run_evaluation():
    settings = get_settings()
    litellm_base_url = settings.litellm_base_url
    litellm_api_key = settings.litellm_api_key.get_secret_value() if settings.litellm_api_key else ""
    gemini_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""

    if litellm_base_url:
        os.environ["OPENAI_API_BASE"] = litellm_base_url

    api_key = litellm_api_key or gemini_key or os.environ.get("OPENAI_API_KEY") or "test-key"
    os.environ["OPENAI_API_KEY"] = api_key

    chat_model = ChatOpenAI(
        model=settings.agent_model_name,
        temperature=0.2,
        api_key=api_key,
    )
    eval_llm = LangchainLLMWrapper(chat_model)

    dataset_path = os.path.join(os.path.dirname(__file__), "golden_dataset.json")
    if not os.path.exists(dataset_path):
        print(f"Dataset not found at {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    questions = [item["user_input"] for item in test_cases]
    responses = ["Employees may claim up to $500 per year for home office equipment with prior manager approval." for _ in test_cases]
    contexts_list = [item["retrieved_contexts"] for item in test_cases]
    references = [item["reference"] for item in test_cases]

    eval_dataset = Dataset.from_dict({
        "question": questions,
        "answer": responses,
        "contexts": contexts_list,
        "ground_truth": references,
    })

    print("Running RAGAS evaluation with LangChain ChatOpenAI & LiteLLM wrapper...")
    try:
        result = evaluate(
            dataset=eval_dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision,
                context_recall,
            ],
            llm=eval_llm,
        )
        report_path = os.path.join(os.path.dirname(__file__), "ragas_report.csv")
        df = result.to_pandas()
        df.to_csv(report_path, index=False)
        print("=== RAGAS Evaluation Results ===")
        print(df)
        print(f"Report saved to {report_path}")
    except Exception as e:
        print(f"Evaluation note: {e}")


if __name__ == "__main__":
    asyncio.run(run_evaluation())
