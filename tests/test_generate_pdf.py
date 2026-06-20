from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from generate_pdf import (
    compile_pdf,
    escape_latex,
    format_timestamp,
    markdown_to_latex,
    render_tex,
    transcript_segments_to_latex,
)


class GeneratePdfTests(unittest.TestCase):
    def test_escape_latex_special_characters(self) -> None:
        escaped = escape_latex("A_B 50% R&D #1 $5 {x} ^ ~ \\")
        self.assertIn(r"A\_B", escaped)
        self.assertIn(r"50\%", escaped)
        self.assertIn(r"R\&D", escaped)
        self.assertIn(r"\textbackslash{}", escaped)

    def test_markdown_subset(self) -> None:
        rendered = markdown_to_latex("## 主题\n- **重点**与`code`\n1. 步骤")
        self.assertIn(r"\subsection{主题}", rendered)
        self.assertIn(r"\textbf{重点}", rendered)
        self.assertIn(r"\texttt{code}", rendered)
        self.assertIn(r"\begin{itemize}", rendered)
        self.assertIn(r"\begin{enumerate}", rendered)

    def test_timestamp_format(self) -> None:
        self.assertEqual(format_timestamp(0), "00:00:00")
        self.assertEqual(format_timestamp(3661.4), "01:01:01")
        self.assertEqual(format_timestamp(-4), "00:00:00")

    def test_timestamped_transcript_blocks(self) -> None:
        rendered = transcript_segments_to_latex(
            [{"start": 597, "end": 1197, "text": "中文原文。"}],
            fallback_text="",
        )
        self.assertIn("00:09:57 -- 00:19:57", rendered)
        self.assertIn("中文原文", rendered)
        self.assertIn(r"\begin{transcriptblock}", rendered)

    @unittest.skipUnless(shutil.which("xelatex"), "xelatex is not installed")
    def test_render_and_compile_chinese_pdf(self) -> None:
        with tempfile.TemporaryDirectory(prefix="audio2pdf-test-") as temp_dir:
            tex_path = Path(temp_dir) / "test.tex"
            render_tex(
                template_path=str(PROJECT_DIR / "templates" / "document.tex"),
                title="中文课程讲稿",
                date_str="2026-06-20",
                organized_md="## 第一章\n- **关键结论**：中文显示正常。",
                raw_text="中文逐字稿。",
                out_tex_path=str(tex_path),
                transcript_segments=[
                    {"index": 0, "start": 0, "end": 600, "text": "中文逐字稿。"}
                ],
            )
            source = tex_path.read_text(encoding="utf-8")
            self.assertNotIn("__TITLE__", source)
            self.assertIn("fontset=fandol", source)

            pdf_path = Path(compile_pdf(str(tex_path)))
            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
