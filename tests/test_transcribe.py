from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from transcribe import format_timestamp, merge_transcripts_with_timestamps


class TranscriptFormattingTests(unittest.TestCase):
    def test_format_timestamp_over_one_hour(self) -> None:
        self.assertEqual(format_timestamp(10739), "02:58:59")

    def test_merge_sorts_and_labels_segments(self) -> None:
        merged = merge_transcripts_with_timestamps(
            [
                {"index": 1, "start": 597, "end": 1197, "text": "第二段"},
                {"index": 0, "start": 0, "end": 600, "text": "第一段"},
            ]
        )
        self.assertLess(merged.index("第一段"), merged.index("第二段"))
        self.assertIn("[片段 01 | 00:00:00 - 00:10:00]", merged)
        self.assertIn("[片段 02 | 00:09:57 - 00:19:57]", merged)


if __name__ == "__main__":
    unittest.main()
