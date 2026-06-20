from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import pipeline


class PipelineResumeTests(unittest.TestCase):
    def test_resume_reuses_json_and_writes_timestamped_transcript(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio2pdf-pipeline-") as temp_dir:
            root = Path(temp_dir)
            input_file = root / "lecture.mp4"
            input_file.write_bytes(b"placeholder")
            output_dir = root / "output"
            work_dir = output_dir / "_work_lecture_20260620-120000"
            work_dir.mkdir(parents=True)
            segments = [
                {"index": 0, "start": 0, "end": 600, "text": "第一段原文。"},
                {"index": 1, "start": 597, "end": 1197, "text": "第二段原文。"},
            ]
            (work_dir / "raw_transcript.json").write_text(
                json.dumps(segments, ensure_ascii=False), encoding="utf-8"
            )
            (work_dir / "raw_transcript.txt").write_text(
                "第一段原文。\n\n第二段原文。", encoding="utf-8"
            )
            config_path = root / "config.yaml"
            config_path.write_text(
                "output:\n  dir: output\n  keep_intermediate: true\n  resume_previous: true\n",
                encoding="utf-8",
            )

            def fake_compile(tex_path: str, engine: str = "xelatex") -> str:
                del engine
                pdf_path = Path(tex_path).with_suffix(".pdf")
                pdf_path.write_bytes(b"%PDF-fake")
                return str(pdf_path)

            with (
                patch.object(pipeline, "validate_environment", return_value=[]),
                patch.object(pipeline, "resolve_api_keys"),
                patch.object(pipeline, "prepare_audio") as prepare_audio,
                patch.object(pipeline, "transcribe_all_chunks") as transcribe_chunks,
                patch.object(pipeline, "correct_transcript", return_value="纠错稿。"),
                patch.object(pipeline, "organize_transcript", return_value="## 笔记\n- 要点"),
                patch.object(pipeline, "compile_pdf", side_effect=fake_compile),
            ):
                result = pipeline.run_pipeline(
                    input_file=input_file,
                    config_path=config_path,
                    output_dir=output_dir,
                )

            prepare_audio.assert_not_called()
            transcribe_chunks.assert_not_called()
            self.assertEqual(result.work_dir, work_dir)
            self.assertIsNotNone(result.timestamped_transcript_path)
            timestamped = result.timestamped_transcript_path.read_text(encoding="utf-8")
            self.assertIn("00:00:00 - 00:10:00", timestamped)
            self.assertIn("00:09:57 - 00:19:57", timestamped)
            tex_source = result.tex_path.read_text(encoding="utf-8")
            self.assertIn("00:09:57 -- 00:19:57", tex_source)


if __name__ == "__main__":
    unittest.main()
