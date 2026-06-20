#!/usr/bin/env python3
"""
main.py
Command line entry point for audio2pdf.

Examples:
    python main.py sample.mp4 --title "Meeting notes"
    python main.py --check --config config.example.yaml
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pipeline import ConfigError, PipelineError, check_setup, run_pipeline


def main():
    parser = argparse.ArgumentParser(description="音频/视频 -> 转写 -> DeepSeek纠错整理 -> LaTeX PDF")
    parser.add_argument("input_file", nargs="?", help="输入的音频或视频文件路径")
    parser.add_argument("--title", default=None, help="文档标题，默认使用文件名")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--output-dir", default=None, help="输出目录，默认读取配置文件 output.dir")
    parser.add_argument("--resume-work-dir", default=None, help="从已有 _work_* 目录继续，避免重新转写")
    parser.add_argument("--no-resume", action="store_true", help="禁用自动断点续跑，强制新建工作目录")
    parser.add_argument("--check", action="store_true", help="只检查本机工具和配置，不调用API")
    parser.add_argument("--require-api-keys", action="store_true", help="配合 --check 使用，要求API key已配置")
    args = parser.parse_args()

    try:
        if args.check:
            for message in check_setup(args.config, require_api_keys=args.require_api_keys):
                print(f"[OK] {message}")
            return

        if not args.input_file:
            parser.error("input_file is required unless --check is used")

        result = run_pipeline(
            input_file=args.input_file,
            title=args.title,
            config_path=args.config,
            output_dir=args.output_dir,
            resume_work_dir=args.resume_work_dir,
            resume_previous=not args.no_resume,
        )
        print("=" * 50)
        print(f"完成：{result.pdf_path}")
        print(f"工作目录：{result.work_dir}")
        print(f"运行日志：{result.log_path}")
    except (ConfigError, PipelineError, RuntimeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
