"""
audio_prep.py
负责：把输入的音频/视频文件统一转换为标准wav，并按时长切分为多段，
避免超出转写API的文件大小/时长限制。

依赖：系统需安装 ffmpeg（brew install ffmpeg / apt install ffmpeg / choco install ffmpeg）
"""
import subprocess
import math
import os
from pathlib import Path


def get_duration_seconds(input_path: str) -> float:
    """用 ffprobe 获取媒体文件总时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def extract_audio_to_wav(input_path: str, output_path: str, sample_rate: int = 16000) -> None:
    """
    从任意音频/视频文件提取单声道16kHz wav（ASR模型标准输入格式）。
    video文件（mp4/mov等）会自动只取音轨。
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ar", str(sample_rate),
        "-ac", "1",
        "-vn",                  # 丢弃视频流
        "-acodec", "pcm_s16le",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def split_into_chunks(
    wav_path: str,
    out_dir: str,
    chunk_minutes: int = 10,
    overlap_seconds: int = 3,
) -> list[dict]:
    """
    把长wav切成若干段，段间有少量重叠，减少句子被切断的概率。
    返回每段的元信息：[{"path": ..., "start": 秒, "end": 秒, "index": 0}, ...]
    """
    os.makedirs(out_dir, exist_ok=True)
    total_duration = get_duration_seconds(wav_path)
    chunk_seconds = chunk_minutes * 60

    chunks = []
    start = 0.0
    idx = 0
    while start < total_duration:
        end = min(start + chunk_seconds, total_duration)
        chunk_path = os.path.join(out_dir, f"chunk_{idx:03d}.wav")

        cmd = [
            "ffmpeg", "-y",
            "-i", wav_path,
            "-ss", str(start),
            "-t", str(end - start),
            "-acodec", "pcm_s16le",
            chunk_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        chunks.append({"path": chunk_path, "start": start, "end": end, "index": idx})

        if end >= total_duration:
            break
        start = end - overlap_seconds  # 下一段往前回退一点，形成重叠
        idx += 1

    return chunks


def prepare_audio(input_path: str, work_dir: str, chunk_minutes: int, overlap_seconds: int) -> list[dict]:
    """对外的主入口：输入任意音视频文件，输出分段后的wav列表"""
    os.makedirs(work_dir, exist_ok=True)
    full_wav = os.path.join(work_dir, "full_audio.wav")
    extract_audio_to_wav(input_path, full_wav)

    chunks_dir = os.path.join(work_dir, "chunks")
    chunks = split_into_chunks(full_wav, chunks_dir, chunk_minutes, overlap_seconds)
    return chunks


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("用法: python audio_prep.py <音频或视频文件路径>")
        sys.exit(1)

    input_file = sys.argv[1]
    work_dir = "./work_" + Path(input_file).stem
    result = prepare_audio(input_file, work_dir, chunk_minutes=10, overlap_seconds=3)
    print(json.dumps(result, indent=2, ensure_ascii=False))
