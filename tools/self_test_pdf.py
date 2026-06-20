#!/usr/bin/env python3
"""
Generate a local Chinese PDF test without relying on terminal encoding.

All Chinese strings use Unicode escapes so PowerShell cannot corrupt the input
before Python receives it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    project_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_dir / "src"))

    from generate_pdf import compile_pdf, render_tex

    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(project_dir / "output" / "_pdf_self_test"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / "audio2pdf_chinese_self_test.tex"

    title = "audio2pdf \u4e2d\u6587 PDF \u81ea\u6d4b"
    organized = (
        "## \u4e2d\u6587\u7ae0\u8282\n"
        "- \u8fd9\u4e00\u9875\u5fc5\u987b\u663e\u793a\u4e2d\u6587\uff0c\u4e0d\u5e94\u8be5\u51fa\u73b0\u95ee\u53f7\u4e71\u7801\u3002\n"
        "- \u7279\u6b8a\u5b57\u7b26\u6d4b\u8bd5\uff1aA_B\u300150%\u3001R&D\u3001#\u6807\u7b7e\u3001$\u6210\u672c\u3002\n"
        "- \u96f6\u5bbd\u5b57\u7b26\u548c\u4e0d\u95f4\u65ad\u7a7a\u683c\u4f1a\u88ab\u6e05\u7406\u3002"
    )
    transcript = (
        "\u8fd9\u662f\u7b2c\u4e00\u6bb5\u4e2d\u6587\u9010\u5b57\u7a3f\uff0c\u7528\u4e8e\u9a8c\u8bc1 PDF \u6b63\u6587\u53ef\u4ee5\u6b63\u5e38\u663e\u793a\u3002\n\n"
        "\u8fd9\u662f\u7b2c\u4e8c\u6bb5\uff0c\u5305\u542b\u7b26\u53f7\uff1a#\u3001$\u3001%\u3001&\u3001_\u3001{\u3001}\u3001^\u3001~\u3002"
    )
    transcript_segments = [
        {"index": 0, "start": 0, "end": 600, "text": transcript},
        {
            "index": 1,
            "start": 597,
            "end": 1197,
            "text": "\u8fd9\u662f\u7b2c\u4e8c\u4e2a\u5e26\u65f6\u95f4\u6807\u8bb0\u7684\u7247\u6bb5\uff0c\u7528\u4e8e\u68c0\u67e5\u5206\u9875\u548c\u4e2d\u6587\u5b57\u4f53\u3002",
        },
    ]

    render_tex(
        template_path=str(project_dir / "templates" / "document.tex"),
        title=title,
        date_str="2026-06-19",
        organized_md=organized,
        raw_text=transcript,
        cjk_font="Microsoft YaHei",
        latin_font="Latin Modern Roman",
        out_tex_path=str(tex_path),
        include_notes=True,
        include_transcript=True,
        transcript_segments=transcript_segments,
    )
    pdf_path = compile_pdf(str(tex_path), engine="xelatex")
    print(pdf_path)


if __name__ == "__main__":
    main()
