from types import SimpleNamespace

from pydantic import SecretStr

from app.core.config import get_llm_config, get_llm_request_options


def test_generic_llm_settings_take_precedence_over_legacy_openai_aliases():
    settings = SimpleNamespace(
        llm_api_key=SecretStr("groq-test-key"),
        llm_api_base="https://api.groq.com/openai/v1",
        llm_model="openai/gpt-oss-20b",
        openai_api_key=SecretStr("old-openai-key"),
        openai_api_base="https://api.openai.com/v1",
        openai_model="gpt-6-luna",
    )
    assert get_llm_config(settings) == (
        "groq-test-key",
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
    )


def test_legacy_openai_settings_remain_supported():
    settings = SimpleNamespace(
        llm_api_key=None,
        llm_api_base="",
        llm_model="",
        openai_api_key=SecretStr("legacy-key"),
        openai_api_base="https://legacy.example/v1",
        openai_model="legacy-model",
    )
    assert get_llm_config(settings) == (
        "legacy-key",
        "https://legacy.example/v1",
        "legacy-model",
    )


def test_blank_generic_key_falls_back_to_legacy_key():
    settings = SimpleNamespace(
        llm_api_key=SecretStr(""),
        llm_api_base="https://api.groq.com/openai/v1",
        llm_model="openai/gpt-oss-20b",
        openai_api_key=SecretStr("legacy-key"),
        openai_api_base="https://api.openai.com/v1",
        openai_model="legacy-model",
    )
    assert get_llm_config(settings) == (
        "legacy-key",
        "https://api.openai.com/v1",
        "legacy-model",
    )



def test_groq_gpt_oss_uses_supported_low_effort_json_options():
    assert get_llm_request_options(
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
    ) == {"reasoning_effort": "low", "reasoning_format": "hidden"}


def test_other_provider_does_not_receive_groq_specific_options():
    assert get_llm_request_options(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-3.8-flash",
    ) == {}
