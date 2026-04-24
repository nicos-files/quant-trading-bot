from __future__ import annotations

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.market_data.crypto_symbols import enabled_crypto_symbols, is_crypto_symbol, load_crypto_universe, normalize_crypto_symbol

from .base import EngineContext, EngineDiagnostics, EngineResult


class IntradayCryptoEngine:
    name = "intraday_crypto"
    horizon = "intraday"

    def run(self, context: EngineContext) -> EngineResult:
        diagnostics = EngineDiagnostics(engine_name=self.name)
        crypto_config = self._load_crypto_config(context)
        provider_name = str(context.metadata.get("crypto_provider_name") or "binance_spot")
        provider_health = context.provider_health.get(provider_name) if isinstance(context.provider_health, dict) else None

        diagnostics.metadata["provider_name"] = provider_name
        diagnostics.metadata["provider_health"] = provider_health

        if crypto_config is None:
            diagnostics.metadata["crypto_symbols_seen"] = []
            diagnostics.metadata["enabled_crypto_symbols"] = []
            diagnostics.metadata["strategy_enabled_count"] = 0
            diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(
                symbol for symbol in (context.universe or []) if not is_crypto_symbol(symbol)
            )
            diagnostics.warnings.append("No crypto universe configured; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        symbols_seen = [str(item.get("symbol") or "").strip().upper() for item in crypto_config if item.get("symbol")]
        enabled_symbols = enabled_crypto_symbols(crypto_config)
        strategy_enabled = [
            normalize_crypto_symbol(item.get("symbol", ""))
            for item in crypto_config
            if item.get("enabled") and item.get("strategy_enabled")
        ]
        diagnostics.metadata["crypto_symbols_seen"] = symbols_seen
        diagnostics.metadata["enabled_crypto_symbols"] = enabled_symbols
        diagnostics.metadata["strategy_enabled_count"] = len([item for item in strategy_enabled if item])
        diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(
            symbol for symbol in (context.universe or []) if not is_crypto_symbol(symbol, crypto_config)
        )
        diagnostics.candidates_seen = len(enabled_symbols)

        if not enabled_symbols:
            diagnostics.warnings.append("No enabled crypto symbols configured; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        if isinstance(provider_health, dict) and provider_health.get("status") == "unhealthy":
            diagnostics.warnings.append("Crypto provider unhealthy; intraday crypto engine remains in no-op mode.")

        if not strategy_enabled:
            diagnostics.warnings.append("Crypto universe detected but strategy disabled; intraday crypto engine skipped.")
            return self._result(context, diagnostics)

        diagnostics.warnings.append("Crypto strategy not implemented yet; engine returned no-op.")
        return self._result(context, diagnostics)

    def _load_crypto_config(self, context: EngineContext) -> list[dict] | None:
        config_payload = context.config.get("crypto_universe")
        if isinstance(config_payload, list):
            return config_payload

        explicit = context.config.get("crypto_symbols")
        if isinstance(explicit, list):
            return [
                {
                    "symbol": normalize_crypto_symbol(symbol),
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "strategy_enabled": False,
                    "paper_enabled": True,
                    "live_enabled": False,
                }
                for symbol in explicit
                if normalize_crypto_symbol(symbol)
            ]

        config_path = context.config.get("crypto_universe_path")
        if config_path:
            return load_crypto_universe(config_path)
        return None

    def _result(self, context: EngineContext, diagnostics: EngineDiagnostics) -> EngineResult:
        diagnostics.candidates_scored = 0
        diagnostics.candidates_rejected = diagnostics.candidates_seen
        return EngineResult(
            engine_name=self.name,
            horizon=self.horizon,
            recommendations=self._empty_output(context),
            diagnostics=diagnostics,
        )

    def _empty_output(self, context: EngineContext) -> RecommendationOutput:
        return RecommendationOutput.build(
            run_id=context.run_id,
            horizon=self.horizon.upper(),
            asof_date=context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
            policy_id=self.name,
            policy_version="1",
            constraints=[],
            sizing_rule="engine.noop",
            recommendations=[],
            cash_summary={},
            cash_policy="engine.noop",
            execution_date=context.metadata.get("execution_date"),
            execution_hour=context.metadata.get("execution_hour"),
            metadata={"engine_name": self.name},
        )
