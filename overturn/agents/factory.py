"""Which extractor reads documents, decided by the environment.

    OVERTURN_EXTRACTOR=model       the extraction agent, in this process
    OVERTURN_EXTRACTOR=agentcore   the extraction agent on Amazon Bedrock AgentCore
                                   (needs OVERTURN_AGENTCORE_ARN)
    unset                          documents are stored and scanned, not read

Every choice writes through the same local ledger writer, so the guarantees do not depend
on where the model runs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from overturn.extraction import Extractor


class ExtractorConfigError(ValueError):
    """The environment asks for an extractor it does not fully describe."""


def extractor_from_env(env: Mapping[str, str] | None = None) -> Extractor | None:
    env = env if env is not None else os.environ
    mode = env.get("OVERTURN_EXTRACTOR", "").strip().lower()

    if mode in ("", "none", "off"):
        return None

    if mode == "model":
        from overturn.agents.extraction import StrandsExtractor
        from overturn.models.factory import build_model

        return StrandsExtractor(lambda: build_model("extraction"))

    if mode == "agentcore":
        arn = env.get("OVERTURN_AGENTCORE_ARN", "").strip()
        if not arn:
            raise ExtractorConfigError(
                "OVERTURN_EXTRACTOR=agentcore needs OVERTURN_AGENTCORE_ARN, the ARN of the "
                "deployed extraction runtime."
            )
        from overturn.agents.remote import AgentCoreExtractor, agentcore_invoker

        return AgentCoreExtractor(
            agentcore_invoker(
                arn,
                region=env.get("AWS_REGION") or None,
                qualifier=env.get("OVERTURN_AGENTCORE_QUALIFIER", "DEFAULT"),
            )
        )

    raise ExtractorConfigError(
        f"Unknown OVERTURN_EXTRACTOR {mode!r}. Expected model, agentcore or unset."
    )
