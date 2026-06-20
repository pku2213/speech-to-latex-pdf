"""
correct_and_organize.py
负责调用 DeepSeek API：
  1. correct_transcript(): 对原始转写文本做"逐字稿纠错"——只修正错字、断句、标点、
     去除因分段重叠导致的重复句子，不改变原意，不做删减总结。
  2. organize_transcript(): 基于纠错后的文本生成"结构化整理稿"——分章节、提炼要点、
     补充小标题，供阅读和复习使用。

长文本会自动按字数切片分别处理，避免超出单次请求的max_tokens限制。
"""
import requests
import hashlib
import time
from pathlib import Path
from typing import Callable


class DeepSeekError(RuntimeError):
    """User-facing API failure that CLI and GUI can report without a traceback."""

    pass


def _deepseek_session(config: dict) -> requests.Session:
    """Create a requests session for DeepSeek.

    The local environment may define HTTP(S)_PROXY for other services. DeepSeek
    often works better directly from this machine, so config can disable proxy
    inheritance with deepseek.proxy_mode: none.
    """
    session = requests.Session()
    proxy_mode = str(config.get("deepseek", {}).get("proxy_mode", "none")).lower()
    if proxy_mode in {"none", "direct", "off", "false"}:
        session.trust_env = False
    return session


def _call_deepseek(
    prompt: str,
    system_prompt: str,
    config: dict,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    ds = config["deepseek"]
    url = f"{ds['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ds['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ds["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": ds.get("max_tokens", 8000),
        "temperature": ds.get("temperature", 0.2),
    }
    max_retries = int(ds.get("max_retries", 6))
    timeout_seconds = int(ds.get("timeout_seconds", 240))
    retry_base_seconds = float(ds.get("retry_base_seconds", 8))
    retry_max_seconds = float(ds.get("retry_max_seconds", 90))

    last_error = None
    session = _deepseek_session(config)
    retryable_status = {408, 409, 425, 429, 500, 502, 503, 504}

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.post(url, headers=headers, json=payload, timeout=timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            last_error = f"DeepSeek API 错误 {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in retryable_status:
                raise DeepSeekError(last_error)
        except (requests.RequestException, ValueError, KeyError) as exc:
            last_error = str(exc)

        if attempt >= max_retries:
            break

        wait = min(retry_max_seconds, retry_base_seconds * (2 ** (attempt - 1)))
        message = f"  [DeepSeek重试] 第 {attempt}/{max_retries} 次失败，{wait:.0f} 秒后重试：{last_error}"
        if progress_callback:
            progress_callback(message)
        else:
            print(message)
        time.sleep(wait)

    raise DeepSeekError(f"DeepSeek API 请求失败，已重试 {max_retries} 次：{last_error}")


def _split_by_length(text: str, max_chars: int = 4000) -> list[str]:
    """按段落边界切分长文本，每片不超过max_chars字符，避免破坏语义"""
    paragraphs = text.split("\n\n")
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) > max_chars and current:
            chunks.append(current)
            current = p
        else:
            current = current + "\n\n" + p if current else p
    if current:
        chunks.append(current)
    return chunks


def _chunk_cache_path(cache_dir: Path, task_name: str, index: int, model: str, system_prompt: str, chunk: str) -> Path:
    digest = hashlib.sha256(f"{task_name}\0{model}\0{system_prompt}\0{chunk}".encode("utf-8")).hexdigest()[:16]
    return cache_dir / task_name / f"{index:03d}_{digest}.txt"


def _run_chunks_with_cache(
    chunks: list[str],
    config: dict,
    task_name: str,
    system_prompt: str,
    cache_dir: str | Path | None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[str]:
    """Run DeepSeek chunks and persist each successful response immediately."""
    cache_root = Path(cache_dir) if cache_dir else None
    model = config.get("deepseek", {}).get("model", "")
    outputs = []

    if cache_root:
        (cache_root / task_name).mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks):
        label = "纠错" if task_name == "correction" else "整理"
        cache_path = _chunk_cache_path(cache_root, task_name, i, model, system_prompt, chunk) if cache_root else None

        if cache_path and cache_path.exists():
            message = f"  [DeepSeek{label}] 复用缓存第 {i + 1}/{len(chunks)} 片"
            if progress_callback:
                progress_callback(message)
            else:
                print(message)
            outputs.append(cache_path.read_text(encoding="utf-8"))
            continue

        message = f"  [DeepSeek{label}] 处理第 {i + 1}/{len(chunks)} 片..."
        if progress_callback:
            progress_callback(message)
        else:
            print(message)

        result = _call_deepseek(chunk, system_prompt, config, progress_callback=progress_callback)
        if cache_path:
            cache_path.write_text(result, encoding="utf-8")
        outputs.append(result)

    return outputs


CORRECTION_SYSTEM_PROMPT = """你是专业的中文语音转写校对员。你会收到一段由ASR（语音识别）自动生成的原始转写文本，
其中可能包含：错别字、漏字、同音字误用、标点缺失或错误、口语化的重复/语气词、以及因分段处理产生的重复句子。

你的任务：
1. 修正明显的错别字、同音字错误（如"在"/"再"、"的"/"地"/"得"混用）。
2. 补全/修正标点符号，合理分段断句。
3. 删除因分段重叠导致的**完全重复**的句子或段落（只删重复部分，不要删减正常内容）。
4. 适度保留口语特征（如"嗯""那个"等语气词可以保留或轻微精简，但不要大幅改写说话人的原意和措辞）。
5. **绝对不要**做总结、删减实质内容、替换专业术语为你认为"更好"的说法、或添加原文没有的信息。
6. 直接输出纠错后的文本，不要加任何前言、解释或markdown标记。"""


ORGANIZE_SYSTEM_PROMPT = """你是专业的笔记整理助手。你会收到一段已经纠错过的会议/讲座逐字稿。

请将其整理为结构清晰的笔记，要求：
1. 根据内容自然划分章节，添加简洁的小标题（用markdown的## 二级标题）。
2. 每个章节下用要点（- 列表）提炼关键信息、结论、行动项（如有）。
3. 保留重要的数字、人名、术语、决策事项，不要遗漏关键信息。
4. 语言精炼书面化，但不要过度概括以致丢失细节。
5. 如果原文中有明显的议程结构（如"第一个议题""下一个问题"等），可作为章节划分依据。
6. 直接输出整理后的markdown内容，不要加额外的前言或解释。"""


def correct_transcript(
    raw_text: str,
    config: dict,
    progress_callback: Callable[[str], None] | None = None,
    cache_dir: str | Path | None = None,
) -> str:
    """对原始转写文本逐字稿纠错，长文本自动分片处理"""
    chunks = _split_by_length(raw_text, max_chars=4000)
    corrected_parts = _run_chunks_with_cache(
        chunks,
        config,
        "correction",
        CORRECTION_SYSTEM_PROMPT,
        cache_dir,
        progress_callback=progress_callback,
    )
    return "\n\n".join(corrected_parts)


def organize_transcript(
    corrected_text: str,
    config: dict,
    progress_callback: Callable[[str], None] | None = None,
    cache_dir: str | Path | None = None,
) -> str:
    """基于纠错后的文本生成结构化整理稿"""
    chunks = _split_by_length(corrected_text, max_chars=6000)
    organized_parts = _run_chunks_with_cache(
        chunks,
        config,
        "organize",
        ORGANIZE_SYSTEM_PROMPT,
        cache_dir,
        progress_callback=progress_callback,
    )
    return "\n\n".join(organized_parts)
