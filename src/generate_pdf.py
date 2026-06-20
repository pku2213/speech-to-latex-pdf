"""Render the audio2pdf LaTeX document and compile it with XeLaTeX.

The renderer deliberately supports a small, predictable Markdown subset. Model
output and ASR text are normalized and escaped before entering LaTeX, while raw
transcript chunks are rendered as breakable boxes with real audio time ranges.
"""
from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Iterable


LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_PATTERN = re.compile("|".join(re.escape(k) for k in LATEX_SPECIAL_CHARS))
_INLINE_MARKDOWN = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*")


def normalize_latex_text(text: str | None) -> str:
    """Remove invisible/control characters that frequently break XeLaTeX."""
    if text is None:
        return ""

    replacements = {
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
        "\u2028": "\n",
        "\u2029": "\n\n",
    }
    normalized = unicodedata.normalize("NFC", str(text))
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    cleaned: list[str] = []
    for char in normalized:
        if char in "\n\t":
            cleaned.append(char)
        elif not unicodedata.category(char).startswith("C"):
            cleaned.append(char)
    return "".join(cleaned)


def escape_latex(text: str | None) -> str:
    """Escape arbitrary user/model text for safe use in LaTeX text mode."""
    normalized = normalize_latex_text(text)
    return _LATEX_PATTERN.sub(lambda match: LATEX_SPECIAL_CHARS[match.group()], normalized)


def inline_markdown_to_latex(text: str) -> str:
    """Convert only bold and inline-code spans, escaping everything else."""
    normalized = normalize_latex_text(text)
    output: list[str] = []
    cursor = 0
    for match in _INLINE_MARKDOWN.finditer(normalized):
        output.append(escape_latex(normalized[cursor:match.start()]))
        token = match.group()
        if token.startswith("**"):
            output.append(r"\textbf{" + escape_latex(token[2:-2]) + "}")
        else:
            output.append(r"\texttt{" + escape_latex(token[1:-1]) + "}")
        cursor = match.end()
    output.append(escape_latex(normalized[cursor:]))
    return "".join(output)


def markdown_to_latex(md_text: str) -> str:
    """Convert the constrained Markdown emitted by the note-organizing prompt."""
    lines = normalize_latex_text(md_text).splitlines()
    output: list[str] = []
    list_mode: str | None = None

    def close_list() -> None:
        nonlocal list_mode
        if list_mode:
            output.append(f"\\end{{{list_mode}}}")
            list_mode = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            output.append("")
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            close_list()
            level = len(heading_match.group(1))
            command = {1: "subsection", 2: "subsection", 3: "subsubsection"}[level]
            output.append(f"\\{command}{{{inline_markdown_to_latex(heading_match.group(2))}}}")
            continue

        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        ordered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if bullet_match or ordered_match:
            desired_mode = "itemize" if bullet_match else "enumerate"
            if list_mode != desired_mode:
                close_list()
                output.append(f"\\begin{{{desired_mode}}}")
                list_mode = desired_mode
            item_text = (bullet_match or ordered_match).group(1)
            output.append(r"\item " + inline_markdown_to_latex(item_text))
            continue

        close_list()
        if stripped in {"---", "***", "___"}:
            output.append(r"\par\smallskip\noindent\textcolor{line}{\rule{\linewidth}{0.5pt}}\par\smallskip")
        elif stripped.startswith("> "):
            output.append(r"\begin{notebox}" + inline_markdown_to_latex(stripped[2:]) + r"\end{notebox}")
        else:
            output.append(inline_markdown_to_latex(stripped) + r"\par")

    close_list()
    return "\n".join(output)


def format_timestamp(seconds: float | int | str | None) -> str:
    """Format seconds as HH:MM:SS without inventing unavailable precision."""
    try:
        total = max(0, int(round(float(seconds or 0))))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _readable_paragraphs(text: str, max_chars: int = 520) -> list[str]:
    """Split ASR text into readable paragraphs without changing its wording."""
    normalized = normalize_latex_text(text).strip()
    if not normalized:
        return []

    source_paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    paragraphs: list[str] = []
    for source in source_paragraphs:
        if len(source) <= max_chars:
            paragraphs.append(source)
            continue
        sentences = [item.strip() for item in _SENTENCE_BOUNDARY.split(source) if item.strip()]
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > max_chars:
                paragraphs.append(current)
                current = sentence
            else:
                current += sentence
        if current:
            paragraphs.append(current)
    return paragraphs


def plain_text_to_latex(text: str) -> str:
    """Render plain text as short paragraphs instead of one unbreakable block."""
    return "\n\n".join(escape_latex(part) + r"\par" for part in _readable_paragraphs(text))


def transcript_segments_to_latex(
    segments: Iterable[dict[str, Any]] | None,
    fallback_text: str,
) -> str:
    """Render transcript chunks with their actual audio start/end timestamps."""
    normalized_segments = list(segments or [])
    if not normalized_segments:
        body = plain_text_to_latex(fallback_text or "暂无逐字稿。")
        return "\\begin{transcriptblock}{时间未记录}\n" + body + "\n\\end{transcriptblock}"

    blocks: list[str] = []
    for display_index, segment in enumerate(normalized_segments, start=1):
        start = format_timestamp(segment.get("start"))
        end = format_timestamp(segment.get("end"))
        label = f"片段 {display_index:02d} · {start} -- {end}"
        text = str(segment.get("text") or "").strip() or "（该时间段未识别到语音内容）"
        blocks.append(
            f"\\begin{{transcriptblock}}{{{escape_latex(label)}}}\n"
            + plain_text_to_latex(text)
            + "\n\\end{transcriptblock}"
        )
    return "\n\n".join(blocks)


def render_tex(
    template_path: str,
    title: str,
    date_str: str,
    organized_md: str,
    raw_text: str,
    cjk_font: str = "",
    latin_font: str = "",
    out_tex_path: str = "",
    include_notes: bool = True,
    include_transcript: bool = True,
    transcript_segments: Iterable[dict[str, Any]] | None = None,
) -> None:
    """Fill the document template with notes and timestamped transcript text.

    ``cjk_font`` and ``latin_font`` remain accepted for compatibility with old
    configs. The template now uses TeX Live's portable Fandol font set.
    """
    del cjk_font, latin_font
    template = Path(template_path).read_text(encoding="utf-8")

    body_parts: list[str] = []
    if include_notes:
        body_parts.append(
            "\\section{整理笔记}\n"
            + markdown_to_latex(organized_md or "暂无整理笔记。")
        )
    if include_transcript:
        if body_parts:
            body_parts.append("\\clearpage")
        body_parts.append(
            "\\section{带时间标记的原文转写}\n"
            "{\\small\n"
            + transcript_segments_to_latex(transcript_segments, raw_text)
            + "\n}"
        )
    if not body_parts:
        body_parts.append("\\section{内容}\n未选择输出内容。\\par")

    filled = (
        template.replace("__TITLE__", escape_latex(title))
        .replace("__DATE__", escape_latex(date_str))
        .replace("__DOCUMENT_BODY__", "\n\n".join(body_parts))
    )
    output_path = Path(out_tex_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(filled, encoding="utf-8", newline="\n")


def _decode_process_output(data: bytes) -> str:
    """Decode TeX output across UTF-8 and common Chinese Windows locales."""
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _latex_error_context(tex_path: Path, process_output: bytes) -> str:
    log_path = tex_path.with_suffix(".log")
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        error_lines = [line for line in log_text.splitlines() if line.startswith("!")]
        tail = "\n".join(log_text.splitlines()[-80:])
        if error_lines:
            return "\n".join(error_lines[-8:]) + "\n\n" + tail
        return tail
    return _decode_process_output(process_output)[-5000:]


def compile_pdf(tex_path: str, engine: str = "xelatex", passes: int = 2) -> str:
    """Compile a UTF-8 LaTeX file and retain .tex/.log for diagnostics."""
    source = Path(tex_path).resolve()
    if not source.exists():
        raise RuntimeError(f"LaTeX 源文件不存在：{source}")

    command = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        "-output-directory=.",
        source.name,
    ]
    for pass_index in range(1, max(1, passes) + 1):
        try:
            result = subprocess.run(
                command,
                cwd=source.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=300,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"找不到 LaTeX 编译器：{engine}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"LaTeX 第 {pass_index} 次编译超过 300 秒，已停止。") from exc

        if result.returncode != 0:
            context = _latex_error_context(source, result.stdout)
            raise RuntimeError(
                f"LaTeX 第 {pass_index} 次编译失败（退出码 {result.returncode}）。\n"
                f"源文件：{source}\n日志摘要：\n{context}"
            )

    pdf_path = source.with_suffix(".pdf")
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"编译命令已结束，但没有生成有效 PDF：{pdf_path}")
    return os.fspath(pdf_path)
