"""
Tests for agents/ori_ia/commentary.py and agents/ori_ia/llm_adapter.py
"""

import pytest

from agents.ori_ia.commentary import build_prompt, generate_commentary
from agents.ori_ia.llm_adapter import (
    CloudAnthropicAdapter,
    CloudOpenAIAdapter,
    LocalLLMAdapter,
    get_adapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_SUMMARY = {
    "total_market_value": 100_000.0,
    "total_cost_basis": 80_000.0,
    "total_unrealized_gain": 20_000.0,
    "total_unrealized_gain_pct": 25.0,
    "position_count": 3,
    "unique_symbols": 3,
    "account_type_split": {"registered": 60_000.0, "non_registered": 40_000.0},
    "sector_weights_pct": {"Technology": 55.0, "Financials": 45.0},
    "concentration_threshold_pct": 10.0,
    "concentration_flags": [{"symbol": "AAPL", "weight_pct": 55.0, "flag": "overweight"}],
    "top_positions": [],
    "positions_summary": [
        {
            "symbol": "AAPL",
            "security_name": "Apple Inc.",
            "sector": "Technology",
            "asset_class": "Equity",
            "market_value": 55_000.0,
            "weight_pct": 55.0,
            "cost_basis": 40_000.0,
            "unrealized_gain": 15_000.0,
            "unrealized_gain_pct": 37.5,
            # Fields that must NOT reach the LLM:
            "registered_value": 55_000.0,
            "non_registered_value": 0.0,
            "unclassified_value": 0.0,
            "account_count": 1,
            "reconciliation_delta": 0.0,
        },
        {
            "symbol": "TD",
            "security_name": "Toronto-Dominion Bank",
            "sector": "Financials",
            "asset_class": "Equity",
            "market_value": 45_000.0,
            "weight_pct": 45.0,
            "cost_basis": 40_000.0,
            "unrealized_gain": 5_000.0,
            "unrealized_gain_pct": 12.5,
            "registered_value": 5_000.0,
            "non_registered_value": 40_000.0,
            "unclassified_value": 0.0,
            "account_count": 2,
            "reconciliation_delta": 0.0,
        },
    ],
    "accounts_loaded": [
        {"file": "acct1.csv", "account_type": "TFSA", "institution": "TD Wealth"}
    ],
}


# ---------------------------------------------------------------------------
# build_prompt — whitelist enforcement
# ---------------------------------------------------------------------------

class TestBuildPromptWhitelist:

    def setup_method(self):
        self.prompt = build_prompt(MINIMAL_SUMMARY)

    def test_whitelisted_symbol_present(self):
        assert "AAPL" in self.prompt

    def test_whitelisted_security_name_present(self):
        assert "Apple Inc." in self.prompt

    def test_whitelisted_sector_present(self):
        assert "Technology" in self.prompt

    def test_whitelisted_asset_class_present(self):
        assert "Equity" in self.prompt

    def test_whitelisted_market_value_present(self):
        # Formatted as "55,000.00" somewhere in the prompt
        assert "55,000.00" in self.prompt

    def test_whitelisted_cost_basis_present(self):
        assert "40,000.00" in self.prompt

    def test_whitelisted_unrealized_gain_present(self):
        assert "15,000.00" in self.prompt

    def test_sensitive_registered_value_absent(self):
        # "registered_value" key must never appear in prompt
        assert "registered_value" not in self.prompt

    def test_sensitive_non_registered_value_absent(self):
        assert "non_registered_value" not in self.prompt

    def test_sensitive_unclassified_value_absent(self):
        assert "unclassified_value" not in self.prompt

    def test_sensitive_account_count_absent(self):
        assert "account_count" not in self.prompt

    def test_sensitive_reconciliation_delta_absent(self):
        assert "reconciliation_delta" not in self.prompt

    def test_institution_name_absent(self):
        # accounts_loaded institution names must not appear
        assert "TD Wealth" not in self.prompt

    def test_account_file_absent(self):
        assert "acct1.csv" not in self.prompt

    def test_portfolio_level_market_value_present(self):
        assert "100,000.00" in self.prompt

    def test_concentration_flag_present(self):
        # AAPL flagged as concentration risk — must appear in alerts section
        assert "AAPL" in self.prompt

    def test_sector_weights_present(self):
        assert "55.0%" in self.prompt or "55.0" in self.prompt

    def test_account_split_present(self):
        # Aggregate split is allowed
        assert "Registered" in self.prompt or "registered" in self.prompt.lower()

    def test_returns_string(self):
        assert isinstance(self.prompt, str)

    def test_prompt_not_empty(self):
        assert len(self.prompt) > 100


class TestBuildPromptEdgeCases:

    def test_empty_summary(self):
        prompt = build_prompt({})
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_none_values_formatted_as_na(self):
        summary = dict(MINIMAL_SUMMARY)
        summary["total_cost_basis"] = None
        prompt = build_prompt(summary)
        assert "N/A" in prompt

    def test_no_positions(self):
        summary = dict(MINIMAL_SUMMARY)
        summary["positions_summary"] = []
        prompt = build_prompt(summary)
        # Should not raise; positions table simply absent
        assert isinstance(prompt, str)

    def test_no_concentration_flags(self):
        summary = dict(MINIMAL_SUMMARY)
        summary["concentration_flags"] = []
        prompt = build_prompt(summary)
        # The Concentration Alerts section header must not appear when there are no flags
        assert "Concentration Alerts" not in prompt

    def test_system_instruction_present(self):
        prompt = build_prompt(MINIMAL_SUMMARY)
        assert "portfolio analyst" in prompt.lower()


# ---------------------------------------------------------------------------
# generate_commentary — mock adapter
# ---------------------------------------------------------------------------

class MockAdapter:
    provider_label = "mock/test"

    def generate(self, prompt: str) -> str:
        return f"**Observations**\n- Mock observation\n\n**Questions**\n- Mock question (prompt_len={len(prompt)})"


class TestGenerateCommentary:

    def test_returns_dict_with_commentary(self):
        result = generate_commentary(MINIMAL_SUMMARY, MockAdapter())
        assert "commentary" in result
        assert isinstance(result["commentary"], str)

    def test_commentary_contains_observations(self):
        result = generate_commentary(MINIMAL_SUMMARY, MockAdapter())
        assert "Observations" in result["commentary"]

    def test_returns_prompt_length(self):
        result = generate_commentary(MINIMAL_SUMMARY, MockAdapter())
        assert "prompt_length" in result
        assert isinstance(result["prompt_length"], int)
        assert result["prompt_length"] > 0

    def test_prompt_length_matches_actual_prompt(self):
        from agents.ori_ia.commentary import build_prompt
        expected_len = len(build_prompt(MINIMAL_SUMMARY))
        result = generate_commentary(MINIMAL_SUMMARY, MockAdapter())
        assert result["prompt_length"] == expected_len

    def test_adapter_receives_non_empty_prompt(self):
        received = []

        class CapturingAdapter:
            provider_label = "capture"
            def generate(self, prompt: str) -> str:
                received.append(prompt)
                return "response"

        generate_commentary(MINIMAL_SUMMARY, CapturingAdapter())
        assert len(received) == 1
        assert len(received[0]) > 100


# ---------------------------------------------------------------------------
# get_adapter — config parsing
# ---------------------------------------------------------------------------

class TestGetAdapterConfig:

    def test_default_returns_local(self):
        adapter = get_adapter({})
        assert isinstance(adapter, LocalLLMAdapter)

    def test_none_config_returns_local(self):
        adapter = get_adapter(None)
        assert isinstance(adapter, LocalLLMAdapter)

    def test_provider_local_explicit(self):
        adapter = get_adapter({"provider": "local"})
        assert isinstance(adapter, LocalLLMAdapter)

    def test_local_custom_model(self):
        adapter = get_adapter({"provider": "local", "local": {"model": "mistral"}})
        assert adapter.model == "mistral"

    def test_local_custom_base_url(self):
        adapter = get_adapter({"provider": "local", "local": {"base_url": "http://127.0.0.1:9999"}})
        assert adapter.base_url == "http://127.0.0.1:9999"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_adapter({"provider": "groq"})

    def test_cloud_unknown_sub_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown cloud provider"):
            get_adapter({"provider": "cloud", "cloud": {"provider": "cohere"}})

    def test_cloud_anthropic_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_adapter({"provider": "cloud", "cloud": {"provider": "anthropic"}})

    def test_cloud_openai_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_adapter({"provider": "cloud", "cloud": {"provider": "openai"}})

    def test_cloud_anthropic_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "anthropic"}})
        assert isinstance(adapter, CloudAnthropicAdapter)

    def test_cloud_anthropic_custom_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        adapter = get_adapter({
            "provider": "cloud",
            "cloud": {"provider": "anthropic", "model": "claude-opus-4-6"},
        })
        assert adapter.model == "claude-opus-4-6"

    def test_cloud_openai_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "openai"}})
        assert isinstance(adapter, CloudOpenAIAdapter)

    def test_cloud_xai_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="XAI_API_KEY"):
            get_adapter({"provider": "cloud", "cloud": {"provider": "xai"}})

    def test_cloud_xai_with_key(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "xai"}})
        assert isinstance(adapter, CloudOpenAIAdapter)

    def test_cloud_xai_base_url(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "xai"}})
        assert adapter.base_url == "https://api.x.ai/v1"

    def test_cloud_xai_default_model(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "xai"}})
        assert adapter.model == "grok-3-mini"

    def test_cloud_xai_custom_model(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
        adapter = get_adapter({"provider": "cloud", "cloud": {"provider": "xai", "model": "grok-3"}})
        assert adapter.model == "grok-3"

    def test_provider_labels(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

        local   = get_adapter({"provider": "local", "local": {"model": "llama3.2"}})
        claude  = get_adapter({"provider": "cloud", "cloud": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"}})
        openai_ = get_adapter({"provider": "cloud", "cloud": {"provider": "openai",    "model": "gpt-4o-mini"}})
        xai_    = get_adapter({"provider": "cloud", "cloud": {"provider": "xai",       "model": "grok-3-mini"}})

        assert "local"     in local.provider_label
        assert "anthropic" in claude.provider_label
        assert "openai"    in openai_.provider_label
        assert "xai"       in xai_.provider_label
