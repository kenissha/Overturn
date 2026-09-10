"""The model layer: roles resolve to providers by configuration alone."""

from __future__ import annotations

import pytest

from overturn.models.factory import (
    ModelConfigError,
    build_model,
    load_config,
    resolve,
)

CONFIG = {
    "default_provider": "bedrock",
    "providers": {"bedrock": {"region": "us-east-1"}, "ollama": {"host": "http://h:1"}},
    "roles": {
        "extraction": {
            "bedrock": "anthropic.claude-opus-5",
            "anthropic": "claude-opus-5",
            "ollama": "llama3.1",
            "max_tokens": 16000,
        }
    },
}


def test_the_shipped_config_loads_and_covers_every_agent_role():
    config = load_config()
    assert {"extraction", "drafting"} <= set(config["roles"])


def test_the_shipped_config_defaults_every_role_to_opus_5():
    config = load_config()
    for spec in config["roles"].values():
        assert spec["anthropic"] == "claude-opus-5"
        assert spec["bedrock"] == "anthropic.claude-opus-5"


def test_sampling_parameters_are_refused_at_load(tmp_path):
    """Claude Opus 5 rejects temperature and top_p; fail at startup, not mid-case."""
    path = tmp_path / "models.yaml"
    path.write_text("roles:\n  extraction:\n    bedrock: x\n    temperature: 0\n")
    with pytest.raises(ModelConfigError, match="sampling"):
        load_config(path)


def test_a_role_resolves_to_the_default_provider():
    choice = resolve("extraction", CONFIG, env={})
    assert choice.provider == "bedrock"
    assert choice.model_id == "anthropic.claude-opus-5"
    assert choice.region == "us-east-1"


def test_the_provider_is_switched_by_environment_alone():
    choice = resolve("extraction", CONFIG, env={"OVERTURN_MODEL_PROVIDER": "anthropic"})
    assert (choice.provider, choice.model_id) == ("anthropic", "claude-opus-5")


def test_a_local_model_keeps_data_on_the_machine():
    choice = resolve("extraction", CONFIG, env={"OVERTURN_MODEL_PROVIDER": "ollama"})
    assert (choice.provider, choice.host) == ("ollama", "http://h:1")


def test_a_model_id_can_be_overridden_per_role():
    choice = resolve(
        "extraction",
        CONFIG,
        env={"OVERTURN_MODEL_ID_EXTRACTION": "us.anthropic.claude-opus-5"},
    )
    assert choice.model_id == "us.anthropic.claude-opus-5"


def test_the_region_follows_aws_region():
    assert resolve("extraction", CONFIG, env={"AWS_REGION": "eu-west-1"}).region == "eu-west-1"


def test_an_unknown_role_is_refused():
    with pytest.raises(ModelConfigError, match="No model configured"):
        resolve("triage", CONFIG, env={})


def test_an_unknown_provider_is_refused():
    with pytest.raises(ModelConfigError, match="Unknown provider"):
        resolve("extraction", CONFIG, env={"OVERTURN_MODEL_PROVIDER": "somewhere"})


def test_a_bedrock_model_is_built_without_calling_aws():
    pytest.importorskip("strands")
    model = build_model("extraction", CONFIG, env={})
    config = model.get_config()
    assert config["model_id"] == "anthropic.claude-opus-5"
    assert config["max_tokens"] == 16000
