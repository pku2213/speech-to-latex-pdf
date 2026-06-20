"""
transcribe.py
负责：调用 Groq 或 硅基流动(SiliconFlow) 的 Whisper/ASR API 完成转写。
两个后端都遵循 OpenAI 兼容的 /audio/transcriptions 接口规范，所以可以共用一套调用逻辑。
"""
import requests
import time
from typing import Callable


class TranscriptionError(Exception):
    pass


def transcribe_chunk(
    chunk_path: str,
    backend_config: dict,
    backend_name: str,
    language: str | None = "zh",
    timeout_seconds: int = 120,
    progress_callback: Callable[[str], None] | None = None,
    max_retries: int = 3,
) -> str:
    """
    转写单个音频片段，返回纯文本。
    backend_config 形如 config["transcription"]["groq"] 或 config["transcription"]["siliconflow"]
    """
    url = f"{backend_config['base_url']}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {backend_config['api_key']}"}

    last_error = None
    for attempt in range(max_retries):
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (chunk_path, f, "audio/wav")}
                data = {
                    "model": backend_config["model"],
                    "response_format": "text",
                }
                if language and language.lower() != "auto":
                    data["language"] = language
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=timeout_seconds)

            if resp.status_code == 200:
                return resp.text.strip()
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except requests.RequestException as e:
            last_error = str(e)

        wait = 2 ** attempt
        message = f"  [警告] 第{attempt + 1}次转写失败，{wait}秒后重试... ({last_error})"
        if progress_callback:
            progress_callback(message)
        else:
            print(message)
        time.sleep(wait)

    raise TranscriptionError(f"转写失败，已重试{max_retries}次: {last_error}")


def transcribe_all_chunks(
    chunks: list[dict],
    config: dict,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    """
    依次转写所有分段，返回带文本的结果列表：
    [{"index": 0, "start": 0.0, "end": 600.0, "text": "..."}, ...]
    """
    backend_name = config["transcription"]["backend"]
    backend_config = config["transcription"][backend_name]
    language = config["transcription"].get("language", "zh")
    max_retries = int(config["transcription"].get("max_retries", 3))
    timeout_seconds = int(config["transcription"].get("timeout_seconds", 120))

    results = []
    total = len(chunks)
    for chunk in chunks:
        message = (f"[转写中] 片段 {chunk['index'] + 1}/{total} "
                   f"({chunk['start']:.0f}s - {chunk['end']:.0f}s) 使用 {backend_name} ...")
        if progress_callback:
            progress_callback(message)
        else:
            print(message)
        text = transcribe_chunk(
            chunk["path"],
            backend_config,
            backend_name,
            language=language,
            timeout_seconds=timeout_seconds,
            progress_callback=progress_callback,
            max_retries=max_retries,
        )
        results.append({
            "index": chunk["index"],
            "start": chunk["start"],
            "end": chunk["end"],
            "text": text,
        })
    return results


def merge_transcripts(results: list[dict]) -> str:
    """
    简单拼接所有分段文本。由于分段间有重叠秒数，DeepSeek纠错阶段会负责
    识别并去除重复的句子片段，这里先做朴素拼接。
    """
    results_sorted = sorted(results, key=lambda r: r["index"])
    return "\n\n".join(r["text"] for r in results_sorted)


def format_timestamp(seconds: float | int | str | None) -> str:
    """Convert an API chunk offset to a stable HH:MM:SS label."""
    try:
        total = max(0, int(round(float(seconds or 0))))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def merge_transcripts_with_timestamps(results: list[dict]) -> str:
    """Create a human-readable transcript while preserving real chunk times."""
    sections = []
    for display_index, result in enumerate(
        sorted(results, key=lambda item: item.get("index", 0)), start=1
    ):
        start = format_timestamp(result.get("start"))
        end = format_timestamp(result.get("end"))
        text = str(result.get("text") or "").strip()
        sections.append(f"[片段 {display_index:02d} | {start} - {end}]\n{text}")
    return "\n\n".join(sections)
