"""The provider-agnostic model layer.

Agents ask for a model by *role* — ``extraction``, ``drafting`` — and this module decides
which provider and model id that means, from ``config/models.yaml`` and the environment.
No agent imports a provider directly, which is what keeps "run it on Bedrock", "run it on
the Anthropic API" and "run it locally, the data never leaves the building" a matter of
configuration.

Provider SDKs are imported lazily, so the deterministic layer and its tests never need
any of them installed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
PROVIDERS = ("bedrock", "anthropic", "ollama")

FORBIDDEN_PARAMS = ("temperature", "top_p", "top_k")
"""Sampling parameters Claude Opus 5 rejects. Refused at config load, not at request time."""


class ModelConfigError(Exception):
    """The model configuration cannot produce a model for the requested role."""


@dataclass(frozen=True, slots=True)
class ModelChoice:
    role: str
    provider: str
    model_id: str
    max_tokens: int
    region: str | None = None
    host: str | None = None


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else CONFIG_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelConfigError(f"No model configuration at {path}") from exc
    if not isinstance(raw, dict) or "roles" not in raw:
        raise ModelConfigError(f"{path.name}: expected a mapping with a 'roles' section")

    for role, spec in raw["roles"].items():
        present = [p for p in FORBIDDEN_PARAMS if p in (spec or {})]
        if present:
            raise ModelConfigError(
                f"{path.name}: role {role!r} sets {present}. Claude Opus 5 rejects sampling "
                "parameters; steer behaviour through the prompt and tools instead."
            )
    return raw


def resolve(
    role: str,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ModelChoice:
    """Decide provider and model id for a role. Pure: no SDK is touched."""
    config = config if config is not None else load_config()
    env = env if env is not None else os.environ

    roles = config.get("roles", {})
    if role not in roles:
        raise ModelConfigError(f"No model configured for role {role!r}. Known: {sorted(roles)}")
    spec = roles[role] or {}

    provider = env.get("OVERTURN_MODEL_PROVIDER") or config.get("default_provider", "bedrock")
    if provider not in PROVIDERS:
        raise ModelConfigError(f"Unknown provider {provider!r}. Expected one of {PROVIDERS}.")

    model_id = env.get(f"OVERTURN_MODEL_ID_{role.upper()}") or spec.get(provider)
    if not model_id:
        raise ModelConfigError(f"Role {role!r} has no model id for provider {provider!r}.")

    settings = (config.get("providers") or {}).get(provider) or {}
    return ModelChoice(
        role=role,
        provider=provider,
        model_id=str(model_id),
        max_tokens=int(spec.get("max_tokens", 16000)),
        region=env.get("AWS_REGION") or settings.get("region"),
        host=settings.get("host"),
    )


def build_model(
    role: str,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Construct a Strands model for a role. Credentials are resolved by each SDK."""
    choice = resolve(role, config, env)

    if choice.provider == "bedrock":
        from strands.models.bedrock import BedrockModel

        return BedrockModel(
            model_id=choice.model_id,
            region_name=choice.region,
            max_tokens=choice.max_tokens,
        )

    if choice.provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(model_id=choice.model_id, max_tokens=choice.max_tokens)

    from strands.models.ollama import OllamaModel

    return OllamaModel(host=choice.host, model_id=choice.model_id)


def describe(role: str) -> str:
    """One line for logs and the trace: which model a role will use, and where."""
    c = resolve(role)
    where = f" in {c.region}" if c.provider == "bedrock" and c.region else ""
    return f"{role}: {c.provider}{where} / {c.model_id}"
