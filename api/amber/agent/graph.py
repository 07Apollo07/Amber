"""LangGraph agent setup routing through LiteLLM proxy."""

import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from amber.agent.tools import vector_search, web_search
from amber.util.config import get_settings


def get_agent_model(settings=None):
    settings = settings or get_settings()
    litellm_base_url = settings.litellm_base_url
    litellm_api_key = settings.litellm_api_key.get_secret_value() if settings.litellm_api_key else ""
    gemini_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""

    if litellm_base_url:
        os.environ["OPENAI_API_BASE"] = litellm_base_url

    api_key = litellm_api_key or gemini_key or os.environ.get("OPENAI_API_KEY") or "test-key"
    os.environ["OPENAI_API_KEY"] = api_key

    model_name = settings.agent_model_name
    return ChatOpenAI(model=model_name, temperature=0.2, streaming=True, api_key=api_key)


def create_agent_graph(checkpointer=None, settings=None):
    settings = settings or get_settings()
    tools = [vector_search, web_search]
    model = get_agent_model(settings).bind_tools(tools)

    def call_model(state: MessagesState):
        print(f"[AGENT_GRAPH] call_model received messages: {state['messages']}")
        system_prompt = SystemMessage(
            content=(
                "You are Amber AI Assistant, an expert helper specialized in assisting users with their personal and internal documents stored in the vector store. "
                "Whenever the user asks a question or makes a request, you must PRIMARILY search the vector store first using `vector_search`. "
                "If the internal documents are insufficient or require additional context, you may then use `web_search` for more info. "
                "Always prioritize internal document knowledge from the vector store."
            )
        )
        messages = [system_prompt] + state["messages"]
        response = model.invoke(messages)
        print(f"[AGENT_GRAPH] call_model generated response: {response}")
        return {"messages": [response]}

    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", tools_condition)
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer)
