from __future__ import annotations

import unittest

from quantagent.retry_utils import jittered_backoff, retry_after_seconds


class RetryUtilsTest(unittest.TestCase):
    def test_retry_after_seconds_parses_positive_numbers(self) -> None:
        self.assertEqual(retry_after_seconds("2"), 2.0)
        self.assertEqual(retry_after_seconds("0.5"), 0.5)
        self.assertIsNone(retry_after_seconds("-1"))
        self.assertIsNone(retry_after_seconds("soon"))
        self.assertIsNone(retry_after_seconds(None))

    def test_jittered_backoff_is_capped_and_positive(self) -> None:
        delay = jittered_backoff(10, base_delay=1.0, max_delay=4.0, jitter_ratio=0.0)

        self.assertEqual(delay, 4.0)
        self.assertGreater(jittered_backoff(1, base_delay=0.1, max_delay=1.0), 0)


if __name__ == "__main__":
    unittest.main()
