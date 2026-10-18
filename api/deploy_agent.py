"""Deployment script for deploying the LangGraph agent to Vertex AI Agent Platform (Agent Engine)."""

import os

import vertexai
from vertexai import agent_engines

from amber.agent.tools import vector_search, web_search


def agent_builder():
    from amber.agent.graph import create_agent_graph
    return create_agent_graph()


def deploy():
    project_id = os.getenv("GCP_PROJECT_ID", "your-gcp-project-id")
    region = os.getenv("GCP_REGION", "us-central1")
    staging_bucket = os.getenv("GCP_STAGING_BUCKET", "gs://your-staging-bucket")

    vertexai.init(project=project_id, location=region, staging_bucket=staging_bucket)

    print("Initializing LanggraphAgent for Vertex AI Agent Platform...")
    
    # We pass the model name, tools, and runnable_builder pointing to our graph builder
    agent = agent_engines.LanggraphAgent(
        model="gemini-2.5-pro",
        tools=[vector_search, web_search],
        runnable_builder=agent_builder,
    )

    print("Deploying agent to Vertex AI Agent Engine (managed runtime)...")
    remote_agent = agent_engines.create(
        agent,
        display_name="amber-langgraph-agent",
        requirements=[
            "langchain-core",
            "langgraph",
            "langchain-openai",
            "httpx",
            "psycopg2-binary",
            "pgvector",
        ],
        extra_packages=["."],
    )

    print("Successfully deployed agent!")
    print(f"Resource Name: {remote_agent.resource_name}")


if __name__ == "__main__":
    deploy()
