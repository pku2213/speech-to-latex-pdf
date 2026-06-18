#!/usr/bin/env python3
"""
extract_audio.py — 从视频中提取音频，或将音频转换为 Whisper 所需格式。

功能：
  1. 检测输入文件是否有音频流（视频 → 提取；纯音频 → 转码）
  2. 输出 16kHz、单声道、PCM 16-bit 的 WAV 文件
  3. stdout 打印输出路径，stderr 打印诊断信息

用法：
  python extract_audio.py <input> [-o output.wav] [--sample-rate 16000] [--channels 1]
"""

import argparse
import subprocess
import sys
from pathlib import Path


def find_ffmpeg():
    """查找 ffmpeg 可执行文件路径。"""
    import shutil
    # 常见 Windows 安装路径
    candidates = [
        "ffmpeg",
        "ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if shutil.which(c):
            return c
    return "ffmpeg"  # 让 subprocess 报错


def probe_file(input_path: Path, ffmpeg: str):
    """
    用 ffprobe 检测文件信息。
    返回 (has_audio: bool, codec_name: str, sample_rate: int, channels: int)
    """
    cmd = [
        ffmpeg.replace("ffmpeg", "ffprobe"),
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(input_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
        if result.returncode != 0:
            # ffprobe 失败，直接假定有音频流，让 ffmpeg 自己报错
            return True, "unknown", 0, 0

        import json
        data = json.loads(result.stdout)
        audio_streams = [
            s for s in data.get("streams", [])
            if s.get("codec_type") == "audio"
        ]
        if not audio_streams:
            return False, "", 0, 0

        s = audio_streams[0]
        return (
            True,
            s.get("codec_name", "unknown"),
            int(s.get("sample_rate", 0)),
            int(s.get("channels", 0)),
        )
    except Exception:
        # 解析失败，保守处理
        return True, "unknown", 0, 0


def extract_audio(
    input_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
    ffmpeg: str = "ffmpeg",
):
    """
    用 ffmpeg 提取/转换音频。
    返回 (success: bool, error_message: str)
    """
    cmd = [
        ffmpeg,
        "-i", str(input_path),
        "-vn",                       # 丢弃视频流
        "-acodec", "pcm_s16le",      # PCM 16-bit 小端
        "-ar", str(sample_rate),     # 采样率
        "-ac", str(channels),        # 声道数
        "-y",                        # 覆盖已有文件
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    if result.returncode != 0:
        # 从 stderr 提取最后几行有意义的错误信息
        error_lines = [l for l in result.stderr.splitlines() if l.strip()]
        relevant = error_lines[-5:] if len(error_lines) > 5 else error_lines
        return False, "\n".join(relevant)
    return True, ""


def main():
    parser = argparse.ArgumentParser(
        description="从视频/音频文件中提取音频并转换为 Whisper 兼容格式"
    )
    parser.add_argument("input", type=Path, help="输入视频或音频文件路径")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="输出 WAV 文件路径（默认：<输入文件名>.wav）")
    parser.add_argument("--sample-rate", type=int, default=16000,
                        help="目标采样率 Hz（默认 16000）")
    parser.add_argument("--channels", type=int, default=1,
                        help="目标声道数（默认 1，单声道）")
    parser.add_argument("--ffmpeg", type=str, default=None,
                        help="ffmpeg 可执行文件路径")

    args = parser.parse_args()

    # 验证输入文件
    if not args.input.exists():
        print(f"[ERROR] 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # 确定输出路径
    if args.output is None:
        args.output = args.input.with_suffix(".wav")
    args.output = args.output.resolve()

    # 查找 ffmpeg
    ffmpeg = args.ffmpeg or find_ffmpeg()
    print(f"[INFO] 使用 ffmpeg: {ffmpeg}", file=sys.stderr)

    # 检测文件
    has_audio, codec, sr, ch = probe_file(args.input, ffmpeg)
    if not has_audio:
        print(f"[ERROR] 文件中没有音频流: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 检测到音频流: codec={codec}, sr={sr}Hz, channels={ch}",
          file=sys.stderr)
    print(f"[INFO] 目标格式: sr={args.sample_rate}Hz, channels={args.channels}, pcm_s16le",
          file=sys.stderr)

    # 执行转换
    ok, error = extract_audio(
        args.input, args.output,
        sample_rate=args.sample_rate,
        channels=args.channels,
        ffmpeg=ffmpeg,
    )

    if not ok:
        print(f"[ERROR] 音频提取失败:\n{error}", file=sys.stderr)
        sys.exit(1)

    # 验证输出
    if not args.output.exists() or args.output.stat().st_size == 0:
        print(f"[ERROR] 输出文件为空或不存在: {args.output}", file=sys.stderr)
        sys.exit(1)

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"[INFO] 音频提取成功: {args.output} ({size_mb:.1f} MB)", file=sys.stderr)
    # stdout 输出路径，供调用者捕获
    print(str(args.output))


if __name__ == "__main__":
    main()
