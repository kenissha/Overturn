"""Amazon Bedrock AgentCore entrypoint for Overturn's extraction agent.

Lives at the repository root so the ``overturn`` package is importable when the runtime
starts. The application itself is defined in overturn/agents/runtime.py; see
deploy/agentcore/README.md for how to deploy it.
"""

from overturn.agents.runtime import build_app

app = build_app()

if __name__ == "__main__":
    app.run()
