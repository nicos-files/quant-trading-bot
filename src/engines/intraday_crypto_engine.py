from __future__ import annotations

from typing import Iterable

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput

from .base import EngineContext, EngineDiagnostics, EngineResult


_CRYPTO_TOKENS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE")


class IntradayCryptoEngine:
    name = "intraday_crypto"
    horizon = "intraday"

    def run(self, context: EngineContext) -> EngineResult:
        diagnostics = EngineDiagnostics(engine_name=self.name)
        crypto_symbols = self._detect_crypto_symbols(context)
        diagnostics.metadata["crypto_symbols_seen"] = list(crypto_symbols)
        diagnostics.metadata["non_crypto_symbols_ignored"] = sorted(set(context.universe) - set(crypto_symbols))

        if not crypto_symbols:
            diagnostics.warnings.append("No crypto symbols configured; intraday crypto engine skipped.")
            return EngineResult(
                engine_name=self.name,
                horizon=self.horizon,
                recommendations=self._empty_output(context),
                diagnostics=diagnostics,
            )

        diagnostics.candidates_seen = len(crypto_symbols)
        diagnostics.warnings.append("Crypto-specific scoring is not implemented yet; engine returned no-op.")
        return EngineResult(
            engine_name=self.name,
            horizon=self.horizon,
            recommendations=self._empty_output(context),
            diagnostics=diagnostics,
        )

    def _detect_crypto_symbols(self, context: EngineContext) -> list[str]:
        explicit = context.config.get("crypto_symbols")
        if isinstance(explicit, list):
            return [str(symbol).strip().upper() for symbol in explicit if str(symbol).strip()]

        universe = [str(symbol).strip().upper() for symbol in (context.universe or []) if str(symbol).strip()]
        detected: list[str] = []
        for symbol in universe:
            if self._looks_like_crypto(symbol):
                detected.append(symbol)
        return detected

    def _looks_like_crypto(self, symbol: str) -> bool:
        upper = symbol.strip().upper()
        if any(token in upper for token in _CRYPTO_TOKENS):
            return True
        if upper.endswith(("-USD", "-USDT", "/USD", "/USDT")):
            base = upper.split("-")[0].split("/")[0]
            return base in _CRYPTO_TOKENS
        return False

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
