"""
Shared audio2pdf pipeline.

This module is the single execution path used by both the command line entry
point and the local browser interface. It validates the local toolchain,
resolves API keys, keeps a run log, and returns all important output paths.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from audio_prep import prepare_audio
from correct_and_organize import correct_transcript, organize_transcript
from generate_pdf import compile_pdf, render_tex
from transcribe import (
    merge_transcripts,
    merge_transcripts_with_timestamps,
    transcribe_all_chunks,
)


ProgressCallback = Callable[[str], None]


class PipelineError(Exception):
    """Base error for user-facing pipeline failures."""


class ConfigError(PipelineError):
    """Raised when configuration or local dependencies are not usable."""


@dataclass
class PipelineResult:
    """Paths produced by one successful audio2pdf run."""

    pdf_path: Path
    tex_path: Path
    work_dir: Path
    log_path: Path
    raw_transcript_path: Path | None
    timestamped_transcript_path: Path | None
    corrected_transcript_path: Path | None
    organized_notes_path: Path | None


DEFAULT_CONFIG: dict[str, Any] = {
    "transcription": {
        "backend": "groq",
        "language": "zh",
        "chunk_minutes": 10,
        "chunk_overlap_seconds": 3,
        "max_retries": 3,
        "timeout_seconds": 120,
        "groq": {
            "api_key": "",
            "api_key_env": "GROQ_API_KEY",
            "model": "whisper-large-v3-turbo",
            "base_url": "https://api.groq.com/openai/v1",
        },
        "siliconflow": {
            "api_key": "",
            "api_key_env": "SILICONFLOW_API_KEY",
            "model": "FunAudioLLM/SenseVoiceSmall",
            "base_url": "https://api.siliconflow.cn/v1",
        },
    },
    "deepseek": {
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "max_tokens": 8000,
        "temperature": 0.2,
        "max_retries": 6,
        "timeout_seconds": 240,
        "retry_base_seconds": 8,
        "retry_max_seconds": 90,
        "proxy_mode": "none",
    },
    "latex": {
        "engine": "xelatex",
        "fontset": "fandol",
    },
    "document": {
        "include_notes": True,
        "include_transcript": True,
    },
    "output": {
        "dir": "./output",
        "keep_intermediate": True,
        "resume_previous": True,
    },
}


PLACEHOLDER_PREFIXES = ("YOUR_", "PASTE_", "REPLACE_")


def _deep_merge(base: dict[str, Any], updates: dict[str, Any] | None) -> dict[str, Any]:
    """Merge nested dictionaries without mutating either input."""
    result = copy.deepcopy(base)
    if not updates:
        return result
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _is_placeholder_key(value: str | None) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    upper = stripped.upper()
    return upper.startswith(PLACEHOLDER_PREFIXES) or upper in {"TODO", "CHANGEME"}


def _read_windows_env_from_registry(env_name: str) -> str:
    """Read a user/machine environment variable saved by setx.

    PowerShell's setx writes future environment values to the registry, but the
    current shell process does not receive them. This fallback lets a same-shell
    `python main.py --check --require-api-keys` succeed after setx.
    """
    if os.name != "nt" or not env_name:
        return ""

    try:
        import winreg
    except ImportError:
        return ""

    locations = [
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ]

    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, env_name)
                return str(value).strip()
        except OSError:
            continue
    return ""


def _resolve_api_key(section: dict[str, Any], label: str, require: bool) -> str | None:
    """Resolve an API key from either config value, env:key syntax, or api_key_env."""
    raw_key = str(section.get("api_key") or "").strip()
    env_name = str(section.get("api_key_env") or "").strip()

    if raw_key.startswith("env:"):
        env_name = raw_key.split(":", 1)[1].strip()
        raw_key = ""

    env_key = os.environ.get(env_name, "").strip() if env_name else ""
    if not env_key and env_name:
        env_key = _read_windows_env_from_registry(env_name)
    resolved = env_key or raw_key

    if require and _is_placeholder_key(resolved):
        hint = f" Set {env_name} or fill api_key." if env_name else " Fill api_key."
        raise ConfigError(f"Missing {label} API key.{hint}")

    if not _is_placeholder_key(resolved):
        section["api_key"] = resolved
        return resolved
    return None


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load YAML config and apply defaults for newly added fields."""
    path = Path(config_path).expanduser()
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    config = _deep_merge(DEFAULT_CONFIG, loaded)
    config["_config_path"] = str(path.resolve())
    return config


def resolve_api_keys(config: dict[str, Any], require: bool = True) -> None:
    """Resolve selected backend and DeepSeek keys in-place."""
    transcription = config["transcription"]
    backend_name = transcription["backend"]
    if backend_name not in transcription or not isinstance(transcription[backend_name], dict):
        raise ConfigError(f"Unsupported transcription backend: {backend_name}")

    _resolve_api_key(transcription[backend_name], f"{backend_name} transcription", require)
    _resolve_api_key(config["deepseek"], "DeepSeek", require)


def validate_environment(config: dict[str, Any]) -> list[str]:
    """Check required local tools and return their resolved executable paths."""
    engine = config["latex"].get("engine", "xelatex")
    required = ["ffmpeg", "ffprobe", engine]
    found: list[str] = []
    missing: list[str] = []

    for command in required:
        resolved = shutil.which(command)
        if resolved:
            found.append(f"{command}: {resolved}")
        else:
            missing.append(command)

    if missing:
        raise ConfigError(
            "Missing required local tool(s): "
            + ", ".join(missing)
            + ". Install ffmpeg/ffprobe and a XeLaTeX-capable TeX distribution."
        )
    return found


def check_setup(config_path: str | Path, require_api_keys: bool = False) -> list[str]:
    """Validate config shape and local tools. API keys are optional by default."""
    config = load_config(config_path)
    messages = validate_environment(config)
    resolve_api_keys(config, require=require_api_keys)

    transcription = config["transcription"]
    backend_name = transcription["backend"]
    backend_key = _resolve_api_key(transcription[backend_name], backend_name, require=False)
    deepseek_key = _resolve_api_key(config["deepseek"], "DeepSeek", require=False)
    messages.append(f"transcription backend: {backend_name}")
    messages.append(f"transcription model: {transcription[backend_name]['model']}")
    messages.append(f"transcription key: {'configured' if backend_key else 'missing'}")
    messages.append(f"deepseek model: {config['deepseek']['model']}")
    messages.append(f"deepseek key: {'configured' if deepseek_key else 'missing'}")
    return messages


def _unique_path(path: Path) -> Path:
    """Return a non-existing path by appending a timestamp when needed."""
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def _find_previous_work_dir(output_dir: Path, stem: str) -> Path | None:
    """Find the newest prior work directory that can resume a failed run."""
    if not output_dir.exists():
        return None

    prefix = f"_work_{stem}_"
    candidates = []
    for path in output_dir.iterdir():
        if not path.is_dir() or not path.name.startswith(prefix):
            continue
        if (path / "raw_transcript.txt").exists() or (path / "raw_transcript.json").exists():
            candidates.append(path)

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _emit(message: str, callback: ProgressCallback | None, log_path: Path | None) -> None:
    """Send progress to stdout/UI and append to the run log."""
    line = str(message)
    if callback:
        callback(line)
    else:
        print(line)
    if log_path:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {line}\n")


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_pipeline(
    input_file: str | Path,
    title: str | None = None,
    config_path: str | Path = "config.yaml",
    progress_callback: ProgressCallback | None = None,
    output_dir: str | Path | None = None,
    resume_work_dir: str | Path | None = None,
    resume_previous: bool | None = None,
) -> PipelineResult:
    """Run audio/video transcription, DeepSeek cleanup, and PDF generation."""
    input_path = Path(input_file).expanduser().resolve()
    if not input_path.exists():
        raise PipelineError(f"Input file not found: {input_path}")

    config = load_config(config_path)
    resolved_output_dir = Path(output_dir or config["output"]["dir"]).expanduser()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    stem = input_path.stem
    should_resume = config["output"].get("resume_previous", True) if resume_previous is None else resume_previous
    resume_dir = Path(resume_work_dir).expanduser() if resume_work_dir else None
    if resume_dir and not resume_dir.exists():
        raise PipelineError(f"Resume work directory not found: {resume_dir}")
    if not resume_dir and should_resume:
        resume_dir = _find_previous_work_dir(resolved_output_dir, stem)

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = resume_dir or (resolved_output_dir / f"_work_{stem}_{run_stamp}")
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "pipeline.log"

    def nested_progress(message: str) -> None:
        _emit(message, progress_callback, log_path)

    _emit("Starting audio2pdf pipeline.", progress_callback, log_path)
    _emit(f"Input: {input_path}", progress_callback, log_path)
    if resume_dir:
        _emit(f"Resume mode: using existing work directory {work_dir}", progress_callback, log_path)

    validate_environment(config)
    resolve_api_keys(config, require=True)
    _emit("Local tools and API configuration validated.", progress_callback, log_path)

    doc_title = title or stem
    date_str = datetime.now().strftime("%Y-%m-%d")

    raw_json_path = work_dir / "raw_transcript.json"
    raw_txt_path = work_dir / "raw_transcript.txt"
    transcript_results: list[dict[str, Any]] | None = None
    if raw_json_path.exists():
        try:
            loaded_results = json.loads(raw_json_path.read_text(encoding="utf-8"))
            if isinstance(loaded_results, list):
                transcript_results = loaded_results
        except (json.JSONDecodeError, OSError) as exc:
            _emit(
                f"Warning: saved transcript JSON could not be read; timestamps may be unavailable: {exc}",
                progress_callback,
                log_path,
            )

    if raw_txt_path.exists():
        _emit("Step 1/5 and 2/5: reusing saved raw transcript; skipping ffmpeg and ASR.", progress_callback, log_path)
        raw_text = raw_txt_path.read_text(encoding="utf-8")
    elif transcript_results is not None:
        _emit("Step 1/5 and 2/5: rebuilding raw transcript from saved JSON; skipping ffmpeg and ASR.", progress_callback, log_path)
        raw_text = merge_transcripts(transcript_results)
        raw_txt_path = _write_text(work_dir / "raw_transcript.txt", raw_text)
    else:
        _emit("Step 1/5: extracting and splitting audio.", progress_callback, log_path)
        chunks = prepare_audio(
            str(input_path),
            str(work_dir),
            int(config["transcription"]["chunk_minutes"]),
            int(config["transcription"]["chunk_overlap_seconds"]),
        )
        _emit(f"Created {len(chunks)} audio chunk(s).", progress_callback, log_path)

        _emit("Step 2/5: calling transcription API.", progress_callback, log_path)
        transcript_results = transcribe_all_chunks(chunks, config, progress_callback=nested_progress)
        raw_text = merge_transcripts(transcript_results)

        if config["output"].get("keep_intermediate", True):
            raw_json_path = _write_json(work_dir / "raw_transcript.json", transcript_results)
            raw_txt_path = _write_text(work_dir / "raw_transcript.txt", raw_text)
        else:
            raw_json_path = None
            raw_txt_path = None
    _emit(f"Raw transcript length: {len(raw_text)} characters.", progress_callback, log_path)

    timestamped_path: Path | None = None
    if transcript_results:
        timestamped_text = merge_transcripts_with_timestamps(transcript_results)
        timestamped_path = _write_text(work_dir / "timestamped_transcript.txt", timestamped_text)
        _emit(
            f"Timestamped transcript prepared with {len(transcript_results)} segment(s).",
            progress_callback,
            log_path,
        )
    else:
        _emit(
            "Timestamp metadata is unavailable; the PDF transcript will be marked as time not recorded.",
            progress_callback,
            log_path,
        )

    corrected_path = work_dir / "corrected_transcript.txt"
    cache_dir = work_dir / "deepseek_cache"
    if corrected_path.exists():
        _emit("Step 3/5: reusing saved corrected transcript.", progress_callback, log_path)
        corrected_text = corrected_path.read_text(encoding="utf-8")
    else:
        _emit("Step 3/5: correcting transcript with DeepSeek.", progress_callback, log_path)
        corrected_text = correct_transcript(
            raw_text,
            config,
            progress_callback=nested_progress,
            cache_dir=cache_dir,
        )
        if config["output"].get("keep_intermediate", True):
            corrected_path = _write_text(work_dir / "corrected_transcript.txt", corrected_text)
        else:
            corrected_path = None
    _emit(f"Corrected transcript length: {len(corrected_text)} characters.", progress_callback, log_path)

    organized_md = ""
    organized_path = work_dir / "organized_notes.md"
    if config.get("document", {}).get("include_notes", True):
        if organized_path.exists():
            _emit("Step 4/5: reusing saved organized notes.", progress_callback, log_path)
            organized_md = organized_path.read_text(encoding="utf-8")
        else:
            _emit("Step 4/5: organizing notes with DeepSeek.", progress_callback, log_path)
            organized_md = organize_transcript(
                corrected_text,
                config,
                progress_callback=nested_progress,
                cache_dir=cache_dir,
            )
            if config["output"].get("keep_intermediate", True):
                organized_path = _write_text(work_dir / "organized_notes.md", organized_md)
            else:
                organized_path = None
        _emit(f"Organized notes length: {len(organized_md)} characters.", progress_callback, log_path)
    else:
        _emit("Step 4/5: skipped organized notes by config.", progress_callback, log_path)
        organized_path = None

    _emit("Step 5/5: rendering LaTeX and compiling PDF.", progress_callback, log_path)
    template_path = Path(__file__).resolve().parent.parent / "templates" / "document.tex"
    tex_path = work_dir / f"{stem}.tex"
    render_tex(
        template_path=str(template_path),
        title=doc_title,
        date_str=date_str,
        organized_md=organized_md,
        raw_text=corrected_text,
        cjk_font=str(config["latex"].get("cjk_font", "")),
        latin_font=str(config["latex"].get("latin_font", "")),
        out_tex_path=str(tex_path),
        include_notes=bool(config.get("document", {}).get("include_notes", True)),
        include_transcript=bool(config.get("document", {}).get("include_transcript", True)),
        transcript_segments=transcript_results,
    )

    compiled_pdf = Path(compile_pdf(str(tex_path), engine=config["latex"]["engine"]))
    final_pdf_path = _unique_path(resolved_output_dir / f"{stem}.pdf")
    shutil.copy2(compiled_pdf, final_pdf_path)
    _emit(f"Finished. PDF: {final_pdf_path}", progress_callback, log_path)

    if not config["output"].get("keep_intermediate", True):
        _emit("Intermediate cleanup is enabled; keeping final PDF only.", progress_callback, log_path)
        shutil.rmtree(work_dir, ignore_errors=True)

    return PipelineResult(
        pdf_path=final_pdf_path,
        tex_path=tex_path,
        work_dir=work_dir,
        log_path=log_path,
        raw_transcript_path=raw_txt_path,
        timestamped_transcript_path=timestamped_path,
        corrected_transcript_path=corrected_path,
        organized_notes_path=organized_path,
    )
