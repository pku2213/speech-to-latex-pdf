# speech-to-latex-pdf

将音频/视频录音通过 Whisper 语音转文字，经 Claude 审校修正后，输出 LaTeX 编译的中文 PDF 转录文档。

## 快速开始

在 Claude Code 中直接说：

```
帮我把这个录音转成 PDF：C:\录音\会议.m4a
```

技能自动执行完整流程：**提取音频 → Whisper 转录 → Claude 审校 → LaTeX 编译 → PDF 输出**

## 工作流

```
音频/视频 (.m4a/.mp3/.mp4/...)
  │
  ├─ [1] extract_audio.py    → ffmpeg 提取音频 → 16kHz mono WAV
  ├─ [2] transcribe.py       → Whisper 语音转文字 → JSON（含时间戳）
  ├─ [3] Claude 审查         → 修正同音字/术语/标点（严格保留原意）
  ├─ [4] 填充 LaTeX 模板     → 转义特殊字符 → .tex 文件
  └─ [5] compile_latex.py    → xelatex 编译 → PDF
```

## 依赖

| 组件 | 用途 | 安装 |
|------|------|------|
| Python 3.10+ | 脚本运行 | — |
| openai-whisper | 本地语音转文字 | `pip install openai-whisper` |
| openai (SDK) | API 备选转录 | `pip install openai` |
| ffmpeg | 音频提取/转换 | `choco install ffmpeg` (Windows) |
| TeX Live (含 xelatex) | PDF 编译 | [tug.org/texlive](https://tug.org/texlive/) |

## 目录结构

```
speech-to-latex-pdf/
├── SKILL.md                    # 技能定义（frontmatter + 工作流指令）
├── LICENSE.txt                 # 许可
├── README.md                   # 本文件
├── scripts/
│   ├── extract_audio.py        # ffmpeg 封装：媒体 → 16kHz mono WAV
│   ├── transcribe.py           # Whisper 封装：local为主 + API备选
│   └── compile_latex.py        # xelatex 封装：.tex → PDF
└── templates/
    └── transcription.tex       # 中文 LaTeX 模板（ctexart + xeCJK）
```

## 功能特性

- **本地优先**：默认使用本地 Whisper，离线可用，隐私安全
- **API 备选**：`--use-api` 切换 OpenAI Whisper API（更高精度）
- **模型降级**：OOM 时自动降级 medium → small → base → tiny
- **中文原生支持**：ctexart + xeCJK，宋体/微软雅黑/仿宋
- **严格逐字转录**：不总结、不省略、不改写原意
- **专业排版**：封面页 + 自动目录 + 蓝色标题 + 时间戳标记
- **附录支持**：可为专业技术录音添加术语对照表
- **特殊字符自动转义**：`& % $ # _ { } ~ ^ \`

## 脚本用法

### extract_audio.py

```bash
python scripts/extract_audio.py <input> [-o output.wav] [--sample-rate 16000]
```

从视频/音频文件中提取音频，转换为 16kHz 单声道 PCM WAV。

### transcribe.py

```bash
python scripts/transcribe.py <audio.wav> [-m medium] [-l zh] [--use-api] [-o output.json]
```

使用 Whisper 将音频转录为 JSON 格式文本。`-m` 可选模型：turbo/large/medium/small/base/tiny。

### compile_latex.py

```bash
python scripts/compile_latex.py <file.tex> [-o output.pdf] [--passes 2]
```

使用 xelatex 编译 .tex 文件为 PDF。编译失败时自动解析 .log 提取错误信息。

## 技术说明

### 中文 LaTeX 方案

模板使用 `ctexart` 文档类 + `xeCJK` 宏包，通过 xelatex 引擎编译，原生支持 CJK 字符。

**页面结构**：
- **封面**：含标题、元数据表（源文件/语言/模型/时长）、整理说明
- **目录**：`\tableofcontents` 自动生成，`\section{}` 标题自动入目录
- **正文**：蓝色 section/subsection 标题，`\timestamp{MM:SS}` 时间标记
- **附录**：可选术语对照表（使用 `longtable` 支持跨页）
- **页眉页脚**：左侧显示文档标题，右侧 "转录文档"，页脚仅页码

默认字体（Windows 11）：
- 正文：宋体 (SimSun)
- 标题：微软雅黑 (Microsoft YaHei) — 蓝色渲染
- 等宽：仿宋 (FangSong)
- 拉丁：Times New Roman / Arial / Consolas

### Whisper 模型选择

| 模型 | 大小 | 速度(CPU) | 中文精度 |
|------|------|-----------|----------|
| tiny | ~75MB | ~8x 实时 | 低 |
| base | ~140MB | ~4x 实时 | 中 |
| small | ~460MB | ~2x 实时 | 较高 |
| medium | ~1.5GB | ~1x 实时 | 高 |
| large | ~2.9GB | ~0.5x 实时 | 最高 |

对于中文技术类录音（如 AFM 操作培训），建议至少使用 medium 模型。日常对话可使用 small。

### 常见问题

**Q: 转录结果有很多错别字？**
A: 尝试更大的 Whisper 模型（`-m medium` 或 `-m large`），或使用 `--use-api` 调用 OpenAI API。

**Q: PDF 编译失败？**
A: 通常是 .tex 中的特殊字符未正确转义。检查 `--keep-aux` 保留 .log 文件查看具体错误。

**Q: 提示模型不支持此 torch 版本？**
A: `openai-whisper` 与较新的 torch 版本可能存在兼容性问题。尝试 `--use-api` 绕过。

## 许可

本技能为 Proprietary 软件。详见 [LICENSE.txt](LICENSE.txt)。

第三方组件：
- openai-whisper: MIT License
- FFmpeg: LGPL/GPL
- TeX Live: 各组件遵循其自由软件许可
