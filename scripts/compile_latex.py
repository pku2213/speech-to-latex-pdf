#!/usr/bin/env python3
"""
compile_latex.py — 使用 xelatex 编译 .tex 文件为 PDF。

功能：
  1. 自动定位 xelatex 可执行文件
  2. 运行多遍编译（默认 2 遍，处理交叉引用）
  3. 编译失败时解析 .log 文件提取错误信息
  4. 成功后清理辅助文件（.aux, .log, .out, .toc）

用法：
  python compile_latex.py <file.tex> [-o output.pdf] [--passes 2] [--keep-aux]
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


# 已知的 xelatex 安装路径（按优先级）
KNOWN_XELATEX_PATHS = [
    r"E:\Mysoftware\TexLive\texlive\2025\bin\windows\xelatex.exe",
    r"C:\texlive\2025\bin\windows\xelatex.exe",
]


def find_xelatex():
    """查找 xelatex 可执行文件。"""
    # 先查已知路径
    for p in KNOWN_XELATEX_PATHS:
        if Path(p).exists():
            return p
    # 再查 PATH
    found = shutil.which("xelatex")
    if found:
        return found
    return None


def parse_latex_errors(log_path: Path, tex_path: Path):
    """
    解析 .log 文件中的 LaTeX 错误。
    返回错误信息列表，每个元素为 (line_number, message)。
    """
    if not log_path.exists():
        return [("?", "未找到 .log 文件")]

    log_content = log_path.read_text(encoding="utf-8", errors="replace")
    errors = []

    # 匹配以 ! 开头的错误行
    lines = log_content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("! "):
            error_msg = line[2:].strip()
            # 获取后续几行作为上下文
            context = []
            for j in range(i + 1, min(i + 10, len(lines))):
                ctx_line = lines[j].strip()
                if ctx_line.startswith("! ") or ctx_line.startswith(")") or not ctx_line:
                    continue
                context.append(ctx_line)
                if len(context) >= 3:
                    break

            # 尝试从上下文中提取行号 (l.123 格式)
            line_num = "?"
            for ctx in context:
                m = re.match(r'l\.(\d+)', ctx)
                if m:
                    line_num = m.group(1)
                    break

            errors.append((line_num, error_msg, context))

    if not errors:
        # 检查是否有 "Fatal error" 等其他失败标记
        for i, line in enumerate(lines):
            if "Fatal error" in line or "Emergency stop" in line:
                errors.append(("?", line.strip(), []))
                break

    return errors


def compile_latex(tex_path: Path, output_pdf: Path, xelatex: str, passes: int):
    """
    编译 LaTeX 文件。
    返回 (success: bool, error_message: str)
    """
    tex_path = tex_path.resolve()
    work_dir = tex_path.parent

    for idx in range(1, passes + 1):
        print(f"[INFO] xelatex 第 {idx}/{passes} 遍编译...", file=sys.stderr)
        cmd = [
            xelatex,
            "-interaction=nonstopmode",
            "-output-directory", str(work_dir),
            str(tex_path.name),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(work_dir),
        )

    # 检查输出 PDF
    default_pdf = tex_path.with_suffix(".pdf")
    if not default_pdf.exists() or default_pdf.stat().st_size == 0:
        # 编译失败，解析错误
        log_path = tex_path.with_suffix(".log")
        errors = parse_latex_errors(log_path, tex_path)

        error_msg = "LaTeX 编译失败:\n"
        for line_num, msg, context in errors[:5]:  # 最多显示5个错误
            error_msg += f"  ! l.{line_num}: {msg}\n"
            for ctx in context[:3]:
                error_msg += f"    {ctx}\n"

        return False, error_msg

    # 移动到目标路径
    if output_pdf.resolve() != default_pdf.resolve():
        import shutil
        shutil.move(str(default_pdf), str(output_pdf))

    return True, ""


def cleanup_aux(tex_path: Path):
    """清理辅助文件。"""
    extensions = [".aux", ".log", ".out", ".toc", ".synctex.gz", ".thm"]
    for ext in extensions:
        aux_file = tex_path.with_suffix(ext)
        if aux_file.exists():
            aux_file.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="使用 xelatex 编译 .tex 文件为 PDF"
    )
    parser.add_argument("tex", type=Path, help="输入 .tex 文件路径")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="输出 PDF 路径（默认: <tex文件名>.pdf）")
    parser.add_argument("--xelatex", type=str, default=None,
                        help="xelatex 可执行文件路径")
    parser.add_argument("--passes", type=int, default=2,
                        help="编译遍数（默认 2，需要交叉引用时可用更多）")
    parser.add_argument("--keep-aux", action="store_true",
                        help="保留辅助文件 (.aux, .log 等)")

    args = parser.parse_args()

    # 验证输入
    if not args.tex.exists():
        print(f"[ERROR] .tex 文件不存在: {args.tex}", file=sys.stderr)
        sys.exit(1)

    if args.tex.suffix.lower() != ".tex":
        print(f"[WARN] 输入文件不是 .tex 扩展名: {args.tex}", file=sys.stderr)

    # 确定输出路径
    if args.output is None:
        args.output = args.tex.with_suffix(".pdf")
    args.output = args.output.resolve()

    # 查找 xelatex
    xelatex = args.xelatex or find_xelatex()
    if xelatex is None:
        print("[ERROR] 未找到 xelatex。请安装 TeX Live 或通过 --xelatex 指定路径。",
              file=sys.stderr)
        print("[ERROR] 检查路径: " + ", ".join(KNOWN_XELATEX_PATHS), file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 使用 xelatex: {xelatex}", file=sys.stderr)
    print(f"[INFO] 输入: {args.tex}", file=sys.stderr)
    print(f"[INFO] 输出: {args.output}", file=sys.stderr)

    # 编译
    ok, error = compile_latex(args.tex, args.output, xelatex, args.passes)

    if not ok:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)

    # 清理辅助文件
    if not args.keep_aux:
        cleanup_aux(args.tex)

    # 验证输出
    if not args.output.exists():
        print(f"[ERROR] PDF 文件未生成: {args.output}", file=sys.stderr)
        sys.exit(1)

    size_kb = args.output.stat().st_size / 1024
    print(f"[INFO] PDF 编译成功: {args.output} ({size_kb:.1f} KB)", file=sys.stderr)
    # stdout 输出路径
    print(str(args.output))


if __name__ == "__main__":
    main()
