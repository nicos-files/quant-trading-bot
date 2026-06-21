import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.engines import IntradayCryptoEngine


class IntradayCryptoQuoteToleranceTests(unittest.TestCase):
    def test_small_future_quote_skew_is_tolerated(self) -> None:
        engine = IntradayCryptoEngine()
        issue = engine._quote_issue(
            {
                "last_price": 100.0,
                "timestamp": "2026-04-21T12:00:01.500000+00:00",
            },
            as_of=datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc),
            max_quote_age_seconds=600.0,
        )
        self.assertIsNone(issue)

    def test_large_future_quote_skew_remains_invalid(self) -> None:
        engine = IntradayCryptoEngine()
        issue = engine._quote_issue(
            {
                "last_price": 100.0,
                "timestamp": "2026-04-21T12:00:03.100000+00:00",
            },
            as_of=datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc),
            max_quote_age_seconds=600.0,
        )
        self.assertIn("quote_invalid:timestamp_in_future", str(issue))


if __name__ == "__main__":
    unittest.main()
