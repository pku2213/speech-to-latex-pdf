#!/usr/bin/env python3
"""
transcribe.py — 使用 Whisper 将音频转录为文字。

支持两种模式：
  1. 本地模式（默认）：使用 openai-whisper 本地模型
  2. API 模式（--use-api）：使用 OpenAI Whisper API

模型降级策略（本地模式）：medium → small → base → tiny
输出 JSON 格式，包含全文和带时间戳的分段信息。

用法：
  python transcribe.py <audio.wav> [-m medium] [-l zh] [-o output.json] [--use-api]
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 模型大小排序，用于降级
MODEL_CASCADE = ["turbo", "large", "medium", "small", "base", "tiny"]


def transcribe_local(
    audio_path: Path,
    model_name: str,
    language: str,
    device: str = "auto",
):
    """
    使用本地 Whisper 模型转录音频。
    返回 (transcript_dict, error_message)
    当 OOM 时返回 (None, "OOM") 以触发降级。
    """
    import whisper

    # 确定实际使用的模型大小（根据 cascade 索引确定可用降级路径）
    try:
        cascade_idx = MODEL_CASCADE.index(model_name)
    except ValueError:
        cascade_idx = 2  # 默认从 medium 开始

    # 尝试从指定模型开始，逐级降级
    for idx in range(cascade_idx, len(MODEL_CASCADE)):
        candidate = MODEL_CASCADE[idx]
        try:
            print(f"[INFO] 加载 Whisper 模型: {candidate} (device={device})",
                  file=sys.stderr)
            model = whisper.load_model(candidate, device=device)
            break
        except Exception as e:
            err_str = str(e).lower()
            if "memory" in err_str or "oom" in err_str or "cuda" in err_str:
                print(f"[WARN] 模型 {candidate} 加载失败(OOM)，尝试降级...",
                      file=sys.stderr)
                continue
            else:
                return None, f"模型加载失败({candidate}): {e}"
    else:
        return None, "所有模型均加载失败（内存不足）。请尝试 --use-api 使用 API 模式。"

    # 执行转录
    print(f"[INFO] 开始转录（使用 {candidate} 模型）...", file=sys.stderr)
    transcribe_start = time.time()

    try:
        # word_timestamps 在 CPU 上很慢，默认关闭
        result = model.transcribe(
            str(audio_path),
            language=language if language != "auto" else None,
            verbose=False,
            word_timestamps=False,
        )
    except Exception as e:
        return None, f"转录失败: {e}"

    elapsed = time.time() - transcribe_start
    duration = result.get("duration", 0)
    speedup = duration / elapsed if elapsed > 0 else 0
    print(f"[INFO] 转录完成: {elapsed:.1f}s (音频时长 {duration:.0f}s, "
          f"速度 {speedup:.1f}x)", file=sys.stderr)

    # 构建标准输出格式
    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "id": seg.get("id", len(segments)),
            "start": round(seg.get("start", 0.0), 2),
            "end": round(seg.get("end", 0.0), 2),
            "text": seg.get("text", "").strip(),
        })

    return {
        "text": result.get("text", "").strip(),
        "language": result.get("language", language),
        "duration": round(duration, 1),
        "segments": segments,
        "model": candidate,
        "source": "local",
    }, ""


def transcribe_api(
    audio_path: Path,
    language: str,
    api_key: str = None,
):
    """
    使用 OpenAI Whisper API 转录音频。
    返回 (transcript_dict, error_message)
    """
    from openai import OpenAI

    # API key: 参数 > 环境变量
    if api_key is None:
        api_key = __import__("os").environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None, "未找到 OpenAI API Key。请设置 OPENAI_API_KEY 环境变量或通过 --api-key 传入。"

    client = OpenAI(api_key=api_key)

    print("[INFO] 使用 OpenAI Whisper API (whisper-1)...", file=sys.stderr)
    transcribe_start = time.time()

    try:
        with open(audio_path, "rb") as f:
            # Whisper API 最大文件 25MB，超过需要分片
            file_size = audio_path.stat().st_size
            if file_size > 25 * 1024 * 1024:
                return None, (
                    f"音频文件过大 ({file_size / 1024 / 1024:.1f} MB > 25 MB)。"
                    f"请使用本地模式或先压缩音频。"
                )

            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=language if language != "auto" else None,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        # 转换为统一格式
        segments = []
        for i, seg in enumerate(getattr(response, "segments", [])):
            segments.append({
                "id": getattr(seg, "id", i),
                "start": round(getattr(seg, "start", 0.0), 2),
                "end": round(getattr(seg, "end", 0.0), 2),
                "text": getattr(seg, "text", "").strip(),
            })

        elapsed = time.time() - transcribe_start
        print(f"[INFO] API 转录完成: {elapsed:.1f}s", file=sys.stderr)

        return {
            "text": getattr(response, "text", "").strip(),
            "language": getattr(response, "language", language),
            "duration": getattr(response, "duration", 0),
            "segments": segments,
            "model": "whisper-1",
            "source": "api",
        }, ""

    except Exception as e:
        return None, f"API 转录失败: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="使用 Whisper 将音频转录为文字（本地优先，API 备选）"
    )
    parser.add_argument("audio", type=Path, help="音频 WAV 文件路径")
    parser.add_argument("-m", "--model", default="medium",
                        choices=MODEL_CASCADE + ["whisper-1"],
                        help="Whisper 模型大小（默认 medium）")
    parser.add_argument("-l", "--language", default="zh",
                        help="语言代码: zh, en, auto（默认 zh）")
    parser.add_argument("--use-api", action="store_true",
                        help="使用 OpenAI Whisper API 代替本地模型")
    parser.add_argument("--api-key", default=None,
                        help="OpenAI API Key（默认读取 OPENAI_API_KEY 环境变量）")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="输出 JSON 文件路径（默认: <音频文件名>_transcript.json）")
    parser.add_argument("--device", default="auto",
                        choices=["auto", "cpu", "cuda"],
                        help="torch 设备（默认 auto）")

    args = parser.parse_args()

    # 验证输入文件
    if not args.audio.exists():
        print(f"[ERROR] 音频文件不存在: {args.audio}", file=sys.stderr)
        sys.exit(1)

    # 确定输出路径
    if args.output is None:
        stem = args.audio.stem
        args.output = args.audio.parent / f"{stem}_transcript.json"
    args.output = args.output.resolve()

    # 执行转录
    if args.use_api:
        transcript, error = transcribe_api(args.audio, args.language, args.api_key)
    else:
        transcript, error = transcribe_local(
            args.audio, args.model, args.language, args.device
        )

    if error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)

    # 写入 JSON
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

    # 打印统计信息
    text_len = len(transcript["text"])
    seg_count = len(transcript["segments"])
    print(f"[INFO] 转录结果: {text_len} 字符, {seg_count} 个分段",
          file=sys.stderr)
    print(f"[INFO] 输出文件: {args.output}", file=sys.stderr)

    # stdout 输出路径
    print(str(args.output))


if __name__ == "__main__":
    main()
