---
name: speech-to-latex-pdf
description: >
  将音频或视频文件转录为中文 LaTeX 编译的 PDF 文档。当用户提供音频/视频文件并要求转写、转录、
  语音转文字、生成转录 PDF、或需要将口语内容整理为文档时触发。支持 .mp3, .wav, .m4a, .aac,
  .ogg, .flac, .wma, .mp4, .mov, .avi, .mkv, .webm 等常见格式。核心原则：严格逐字转录，
  不做总结、不省略内容、不改写原意。不要在使用场景是摘要/总结时触发 — 此技能只做完整转录。
license: Proprietary. See LICENSE.txt for complete terms.
---
# speech-to-latex-pdf — 音频/视频 → 转录 PDF

## 概述

此技能将口语录音转换为专业排版的 PDF 转录文档。工作流：接收媒体文件 →
提取音频 → Whisper 语音转文字 → Claude 审查修正错别字 → 生成 LaTeX → xelatex 编译 PDF。

所有输出严格按照原录音内容，不总结、不改写、不省略。

## 依赖检查

开始前，逐项验证以下依赖（任一失败则终止并告知用户修复方法）：

| 检查项 | 命令 | 失败时的安装建议 |
|--------|------|-----------------|
| ffmpeg | `ffmpeg -version` | `choco install ffmpeg` |
| xelatex | `xelatex --version` | 安装 TeX Live |
| openai-whisper | `python -c "import whisper; print(whisper.__version__)"` | `pip install openai-whisper` |
| openai SDK | `python -c "import openai; print(openai.__version__)"` | `pip install openai` |

这些依赖已在 Windows 11 + Python 3.13.5 环境中验证通过。

## 工作流

严格按以下 6 步执行，每步完成后再进行下一步。

---

### 第 1 步：接收输入并确定文件信息

用户提供媒体文件路径。确认：
- 文件是否存在
- 文件类型（音频或视频，根据扩展名判断）
- 输出文件名的 stem（不含扩展名），用于后续步骤的命名

例如 `C:\meetings\interview.mp4` → stem = `interview`

询问用户（如未指定）：
- **标题**：PDF 文档标题（默认使用文件名）
- **录音日期**：原始录音的日期（默认用今天）
- **语言**：录音语言（默认 `zh`）
- **模型**：Whisper 模型大小（默认 `medium`；长录音可用 `small` 提速）

---

### 第 2 步：提取音频

运行音频提取脚本，将媒体文件转为 16kHz mono WAV：

```
python "C:\Users\z\.claude\skills\speech-to-latex-pdf\scripts\extract_audio.py" "<输入文件>" -o "<stem>.wav"
```

- stdout 输出 WAV 文件路径，捕获为 `$wav_path`
- 如果返回非 0 退出码，查看 stderr 错误信息，参考错误恢复表处理

常见错误处理：
- **没有音频流** → 告知用户此文件不含音频
- **ffmpeg 未找到** → 指引安装 ffmpeg
- **文件损坏/不支持的编码** → 告知用户文件格式问题

---

### 第 3 步：语音转文字

运行转录脚本：

```
python "C:\Users\z\.claude\skills\speech-to-latex-pdf\scripts\transcribe.py" "<wav路径>" -m <模型> -l <语言> -o "<stem>_transcript.json"
```

- stdout 输出 JSON 文件路径
- 如果用户明确要求使用 API，添加 `--use-api` 参数（需要 `OPENAI_API_KEY` 环境变量）

**模型降级**：如果本地模型加载 OOM，脚本自动降级（medium → small → base → tiny）。如果全部失败，提示用户使用 `--use-api`。

转录完成后，**必须用 Read 工具读取 JSON 文件获取转录文本**。

---

### 第 4 步：Claude 审查和修正

这是最关键的一步。读取转录 JSON 后，你需要：

**必须修正的错别字类型：**
1. **中文同音字错误**（最常见）：如 "是/事/试/市/式"、"在/再"、"的/地/得"
2. **专有名词**：人名、地名、机构名、专业术语（根据上下文推断正确写法）
3. **标点符号**：补充缺失的句读、修正错误标点
4. **数字和单位**：确保数字转写正确（如 "一百二十" vs "120" — 保持一致）
5. **中英混排**：修正中英文之间的空格、大小写

**绝对不能做的：**
- ❌ 总结或缩写内容
- ❌ 改写或润色原文表述
- ❌ 删除"嗯"、"啊"等填充词（除非用户要求）
- ❌ 合并或拆分段落的原始结构
- ❌ 添加原文没有的信息或评论

修正后将全文保存到变量中，作为 LaTeX 正文内容。

---

### 第 5 步：生成 LaTeX 文档

读取 LaTeX 模板：
```
C:\Users\z\.claude\skills\speech-to-latex-pdf\templates\transcription.tex
```

替换所有占位符：

| 占位符 | 替换内容 |
|--------|---------|
| `TITLE_PLACEHOLDER` | 转录标题（用户指定或从文件名推断，**出现在多个位置需全部替换**） |
| `DATE_PLACEHOLDER` | 整理日期（当前日期，YYYY-MM-DD） |
| `RECORDING_DATE_PLACEHOLDER` | 原始录音日期（用户指定或默认今天） |
| `SOURCE_FILE_PLACEHOLDER` | 原始媒体文件名 |
| `LANGUAGE_PLACEHOLDER` | 语言（如 "中文 (zh)"） |
| `MODEL_PLACEHOLDER` | Whisper 模型名（如 "medium" 或 "whisper-1"） |
| `DURATION_PLACEHOLDER` | 音频时长（如 "约 33 分钟"） |
| `SEGMENT_COUNT_PLACEHOLDER` | 分段数量 |
| `TRANSCRIPT_BODY_PLACEHOLDER` | 修正后的转录正文 |
| `APPENDIX_PLACEHOLDER` | 附录内容（如无附录则留空或注释掉） |

**转录正文格式**：
- 使用 `\section{}` 作为大段落标题（会出现在目录中）
- 如有时间戳，用 `\timestamp{MM:SS}` 命令标记时间
- 段落间用空行分隔，LaTeX 会自动处理间距
- 示例结构：
  ```latex
  \section{装针与激光安全}
  \timestamp{00:00}
  
  通常就是拿左手扣入这个，然后右手给它扶着往上走...
  
  \section{软件操作流程}
  \timestamp{02:00}
  
  接下来我们是按照这边这个顺序来...
  ```

**附录（可选）**：
- 如果转录内容涉及专业技术术语，可在 `APPENDIX_PLACEHOLDER` 处添加术语对照表
- 使用 `\section{附录：术语对照}` 格式
- 术语表用 `longtable` 环境（支持跨页）

**特殊字符转义**：写入 .tex 前，必须转义以下字符：

| 字符 | 替换为 |
|------|--------|
| `&` | `\&` |
| `%` | `\%` |
| `$` | `\$` |
| `#` | `\#` |
| `_` | `\_` |
| `{` | `\{` |
| `}` | `\}` |
| `~` | `\textasciitilde{}` |
| `^` | `\textasciicircum{}` |
| `\` | `\textbackslash{}` |

将填充后的 .tex 文件写入 `<stem>.tex`。

---

### 第 6 步：编译 PDF

```
python "C:\Users\z\.claude\skills\speech-to-latex-pdf\scripts\compile_latex.py" "<stem>.tex" -o "<stem>.pdf"
```

如果编译失败：
1. 读取错误输出中的 LaTeX 错误信息
2. 根据提示的行号和内容定位 .tex 文件中的问题
3. 修正错误（通常是特殊字符未正确转义）
4. 重新编译，最多重试 3 次
5. 如 3 次后仍失败，向用户报告具体错误

如果编译成功：
1. 确认 PDF 文件路径和大小
2. 告知用户结果
3. 询问是否需要清理中间文件（.wav, .json, .tex, .aux, .log）

---

### 第 7 步：交付

最终输出：
- **PDF 文件**：`<stem>.pdf`，在用户当前工作目录
- **反馈摘要**：包含文件大小、页数（估算）、转录字符数

---

## 错误恢复表

| 错误 | 原因 | 恢复方案 |
|------|------|---------|
| ffmpeg not found | 未安装 ffmpeg | 指引用户 `choco install ffmpeg` |
| xelatex not found | 未安装 TeX Live | 指引用户安装 TeX Live 或提供 --xelatex 路径 |
| No audio stream | 文件不含音频轨 | 告知用户，确认文件正确 |
| CUDA/CPU OOM on load | 内存不足加载大模型 | 提示用户用 `-m small` 或 `--use-api` |
| API rate limit | OpenAI 配额不足 | 等待后重试，或回退到本地模型 |
| API auth error | API key 无效 | 提示检查 OPENAI_API_KEY |
| LaTeX compilation error | .tex 语法错误 | 读取 .log，修正未转义字符，重编译 |
| Corrupted audio file | 文件损坏 | 终止并告知用户文件问题 |
| Empty transcript | 音频无有效语音 | 警告用户，可能为静音文件 |

---

## 脚本参考

所有脚本位于 `C:\Users\z\.claude\skills\speech-to-latex-pdf\scripts\`：

| 脚本 | 功能 | 关键参数 |
|------|------|---------|
| `extract_audio.py` | 提取/转换音频为 16kHz mono WAV | `input`, `-o`, `--sample-rate`, `--channels` |
| `transcribe.py` | Whisper 语音转文字 | `audio`, `-m`, `-l`, `--use-api`, `--api-key`, `-o` |
| `compile_latex.py` | xelatex 编译为 PDF | `tex`, `-o`, `--passes`, `--keep-aux` |

所有脚本：
- stdout 输出最终文件路径（供捕获）
- stderr 输出进度和诊断信息
- 使用 `python <脚本路径> <参数>` 调用

---

## 中文支持说明

- LaTeX 模板使用 `ctexart` 文档类 + `xeCJK` 宏包
- 默认字体：宋体（正文）、微软雅黑（标题）、仿宋（等宽）
- 拉丁字符配套：Times New Roman + Arial + Consolas
- 编译引擎：xelatex（必需，pdflatex 不支持 CJK）
- 所有字体均为 Windows 11 系统默认字体，无需额外安装

## 模板特性

- **封面**：标题页含元数据表（源文件、语言、模型、时长、分段数）
- **目录**：`\tableofcontents` 自动生成，`\section{}` 标题自动入目录
- **蓝色标题**：所有 section/subsection 使用蓝色（RGB 0,90,160）
- **时间戳**：`\timestamp{MM:SS}` 命令在段落前标记录音时间点
- **页眉页脚**：页眉左侧显示文档标题，页脚仅显示页码
- **附录支持**：可为专业录音添加术语对照表或补充说明
