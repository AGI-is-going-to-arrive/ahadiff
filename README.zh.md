# 知返 AhaDiff

> **读懂这次变化。**
>
> 从 Git 改动、两份文件、粘贴的 diff、本地快照或单份 Markdown 中学习。对照证据阅读讲解，回答问题，过一段时间再复习。

[English](https://github.com/AGI-is-going-to-arrive/ahadiff/blob/main/README.md) · [介绍页](https://agi-is-going-to-arrive.github.io/ahadiff/) · [使用指南](https://agi-is-going-to-arrive.github.io/ahadiff/USER_GUIDE.zh.html) · [v1.4.0 发布说明](https://github.com/AGI-is-going-to-arrive/ahadiff/releases/tag/v1.4.0) · [英文视频](https://youtu.be/lvL7GMvDPvI) · [中文视频](https://www.bilibili.com/video/BV1b57k6yEWm)

知返把课程和复习记录保存在你的工作目录中。自己的修复、同事的修改、AI 生成的代码都能用来学习。文件、补丁、快照和文档学习无需 Git。

## 1.4.0 新增内容

- **五种 WebUI 学习入口。** 选择 Git 改动、两份文件、粘贴 diff、本地快照或单份 Markdown。发送生成请求前，先在本地预览来源。
- **本地快照。** 保存一份旧文件作为对比基准，之后再与新版比较。知返保存脱敏后的副本，不改写原文件。
- **文档与格式证据。** 学习单份 Markdown，或在对比中沿引用找到 Markdown 章节、Notebook 单元格，以及 JSON/TOML/YAML 键路径。
- **主动迁移练习。** 生成预测结果、补全相似示例、解释错误的开放题。先作答，再对照参考答案评估自己的理解。
- **更清楚的模型设置。** 设置页区分“模型默认”和“关闭思考”，只展示受支持的选项，并在保存前预览模型限制。

## 安装或升级

需要 Python 3.11+ 和兼容的 SQLite 运行时。选择下面一种隔离安装方式，即可安装 CLI 和配套 WebUI：

```bash
pipx install ahadiff
# 或
uv tool install ahadiff

ahadiff --version
# ahadiff 1.4.0
```

已经安装？先停止正在运行的 AhaDiff 服务，用原来的安装工具升级，再重新启动：

```bash
pipx upgrade ahadiff
# 或
uv tool upgrade ahadiff
```

在虚拟环境或 conda 环境中，可用 `python -m pip install ahadiff` 安装，用 `python -m pip install --upgrade ahadiff` 升级。如果 pip 提示 `externally-managed-environment`，请改用 pipx、uv tool 或虚拟环境。

每个工作目录下的 `.ahadiff/` 保存学习记录。升级前请备份该目录。备份可能包含源码片段和提供商凭证，请私下保存。

可选的 `optimizer` 扩展会安装 torch，用于优化 FSRS 参数。基础复习和排程无需此扩展；需要时可用 `pipx install 'ahadiff[optimizer]'` 或 `uv tool install 'ahadiff[optimizer]'` 安装。

## 生成第一节课

在准备保存学习记录的目录中打开终端：

```bash
ahadiff serve
```

知返会按需创建本地数据，并打开 `http://127.0.0.1:8765`。加上 `--no-browser` 可只启动服务。普通文件夹也能用；`ahadiff init` 和 `ahadiff doctor` 用于 Git 仓库。

1. 打开 **设置**，添加本地或远程模型提供商，选择生成模型。若配置了多个提供商，请选定要使用的一个。需要模型点评课程质量时，再单独设置评判提供商。
2. 打开 **欢迎页**、**快速开始** 或 **使用指南**，从下表选择来源。
3. 预览来源。预览前可添加 **Review 说明**，或勾选 **此来源的更多选项 → 主动迁移练习**。预览不调用 LLM；**开始学习** 会使用已配置的提供商和隐私模式。
4. 阅读 **课程**，沿链接查看来源证据。先回答 **测验**，再揭示参考答案；卡片到期后，回到 **复习**。

| 手上有什么 | 选择 | 示例 |
| --- | --- | --- |
| Git 仓库中的修改 | **Git 改动** | bug 修复、评审过的提交、AI 修改 |
| 修改前和修改后的文件 | **两份文件** | 代码、SQL、配置、Markdown、两版 Notebook |
| 从工具复制的统一 diff | **粘贴改动** | 评审补丁、别人分享的修改 |
| 想反复使用的旧文件 | **本地快照** | 先保存旧版，再选择新版 |
| 一份 Markdown 文档 | **单份 Markdown** | 无需旧版，直接学习标题和段落 |

对比两份文件时，把各版本选入或拖入对应区域；文件名可以相同。浏览器选择的文本文件每份上限 256 KiB，两份合计 512 KiB。快照和单份 Markdown 在 CLI 与 WebUI 中都保持 256 KiB 上限。粘贴 diff 上限为 64 KiB。预览最多显示 64 KiB，超出时会提示截断。

文件、补丁、快照和文档入口默认勾选 **小改动也生成课程**，你可以取消。这个选项只跳过可学习性筛选，证据和安全检查仍然生效。

## 使用终端

先在设置中配置提供商。把输入文件放在工作目录内，再选择相应命令：

```bash
# 对比两份文本文件
ahadiff learn --compare before.py after.py --force-learn

# 读取统一 diff
ahadiff learn --patch change.diff --force-learn

# 学习单份 Markdown
ahadiff learn --document notes.md --force-learn

# 生成开放式迁移题
ahadiff learn --compare before.py after.py --force-learn --active-practice

# 学习最近一次 Git 提交
ahadiff learn --last
```

保存并复用快照：

```bash
ahadiff snapshot save before.py --name before-refactor
ahadiff snapshot list
ahadiff learn --snapshot SNAPSHOT_ID --after after.py --force-learn
```

将 `SNAPSHOT_ID` 替换为 `snapshot save` 或 `snapshot list` 输出的 ID。快照是脱敏后的学习基准，不是完整文件备份。保存、对比和删除快照都不会覆盖原文件；删除快照也会保留之前的课程。

运行结束后，使用输出中的 `RUN_ID`：

```bash
ahadiff quiz RUN_ID
ahadiff review
ahadiff export preview RUN_ID --out ./preview
```

[使用指南](https://agi-is-going-to-arrive.github.io/ahadiff/USER_GUIDE.zh.html) 还介绍了 Git 提交范围、工作区捕获、补丁 URL、目录对比、Review 说明、重新生成测验和导出方式。

## 模型与隐私

可以使用 LM Studio、Ollama 等本地提供商，也可以自备密钥接入 OpenAI、Anthropic、Gemini、Azure、NewAPI 或 OpenAI 兼容服务。提供商类型包括 `openai`、`openai_responses`、`gemini`、`anthropic`、`azure`、`newapi`、`openai_compat`、`lmstudio`、`ollama`。请选择与你的接口协议相符的类型。

设置页可以把提供商保存在当前工作目录或全局配置中。同名时，工作目录中的别名覆盖全局别名。生成与评判模型可以使用不同提供商。限制预览只读取本地注册表和配置；测试提供商会发送小型真实请求，可能产生费用。

保留 **模型默认** 时，思考行为由提供商决定。只有支持关闭思考的模型和接口才提供 **关闭**。其他模型可能提供等级、开关，或不提供思考选项。模型出现在目录中，不代表你的账号能调用它。

默认隐私模式为 `strict_local`。使用远程提供商前，请选择 `redacted_remote` 或 `explicit_remote`。开始远程运行前，检查来源和脱敏结果。知返会检查密钥与可疑指令，你仍需检查准备发送的内容。

在设置中粘贴密钥后，知返将其保存在所选范围的 `.env` 中，`config.toml` 只保留环境变量引用。工作目录提供商使用 `.ahadiff/.env`；全局提供商使用操作系统配置目录，具体路径见 [使用指南](https://agi-is-going-to-arrive.github.io/ahadiff/USER_GUIDE.zh.html#provider)。使用全局配置时，请单独备份。工作目录的忽略规则会防止普通 `git add` 纳入密钥文件。你也可以通过 `api_key_env` 指定系统环境变量。macOS/Linux 上的密钥文件仅限所有者访问；Windows 上请用 NTFS 权限保护目录。分享压缩包时，请排除密钥文件和私人备份。

## 查看学习结果

- **课程与证据：** 可以选择提示、精简或完整讲解。查看每条声明的来源和证据状态：已验证、弱证据、未证明、被反驳或已拒绝。引用能确认原文与位置，不能证明外部事实或运行时行为。
- **测验与复习：** 默认混合引导题、回忆题和迁移题。主动迁移练习会生成预测、补全和解释错误的开放题。选择题由程序检查；开放题由你对照参考答案自评。知返不执行练习代码。练习统计记录作答和自评，不代表已测得学习提升。
- **评分与评判：** 确定性评分包含八个维度，并检查必需的证据与安全条件。分数高也可能因必需条件不满足而失败。可选的 LLM 评判提供反馈，不覆盖最终结论。文档运行的 Diff 覆盖度和变更新颖度可学习性显示 N/A；未提供规范时，规范对齐显示 N/A。
- **概念与导出：** 跨运行查看概念，导出本地 HTML 预览，把复习卡下载为 Anki `.apkg`，或导出 TSV/JSON 数据。分享预览前，请检查其中的私人源码内容。
- **改进课程：** `ahadiff improve-run RUN_ID` 会尝试生成新课程，只有确定性评分提高时才保存为独立运行，原运行继续保留。另一个命令 `ahadiff improve` 用于修改 AhaDiff 自身的生成提示词，需要在 AhaDiff 源码目录中运行。

## 可选的 AI 工具集成

安装 AhaDiff 后，可以为所用编程工具写入项目指引：

```bash
ahadiff install --detect
ahadiff install codex --dry-run
ahadiff install codex
# 其他目标包括 claude、cursor、copilot、pi、grok 和 devin
```

**设置 → AI 工具指引** 展示当前支持的工具，并在写入、更新或移除前预览文件。**使用指南** 提供对应说明。这些命令写入项目指引，不会安装第三方工具或登录账号。卸载只移除 AhaDiff 生成的文件和标记段，保留其他指引。

在 macOS/Linux 的 Git 工作流中，`ahadiff install hooks` 会在提交后提醒学习；加上 `--auto-learn` 可在后台生成课程。`ahadiff watch` 监听工作区修改并学习；`ahadiff serve --watch` 同时启动 WebUI。自动学习可能反复调用提供商，启用前请检查隐私和预算设置。

也可以连接只读 MCP 服务：

```bash
claude mcp add ahadiff -- ahadiff mcp-server --repo-root /path/to/workspace
codex mcp add ahadiff -- ahadiff mcp-server --repo-root /path/to/workspace
```

## 环境要求与限制

- **Python 与 SQLite：** 使用 Python 3.11+，SQLite 需要 3.51.3+，或已修补的 3.50.4+ / 3.44.6+ 分支。SQLite 3.51.0–3.51.2 不满足要求。可在 **快速开始** 中查看 AhaDiff 实际使用的运行时；Git 仓库内也可运行 `ahadiff doctor`。
- **平台：** 核心 CLI 和 WebUI 面向 macOS、Linux 与 Windows。目录对比（`--compare-dir`）和 Git hooks 需要 macOS/Linux。已测试平台与已知问题见 [发布说明](https://github.com/AGI-is-going-to-arrive/ahadiff/releases/tag/v1.4.0)。
- **输入：** 单文档学习接受本地 `.md` / `.markdown` 文件，暂不支持 PDF 或网页抓取。Notebook 对比只读取单元格源码，不执行 Notebook。
- **证据：** 不支持的结构可能回退到较弱的行级证据。Review 说明只补充背景，不充当证明。旧运行保留原有证据格式。
- **语言：** WebUI 和生成的学习材料支持中英文。CLI 帮助和大多数诊断使用英文。

## 界面示例

以下示例来自早期界面。五种来源的当前操作请以上文为准。

<p align="center">
  <img src="https://raw.githubusercontent.com/AGI-is-going-to-arrive/ahadiff/main/docs/video/public/screenshots/zh/zh-dashboard.png" alt="仪表盘展示课程运行、评分和复习记录" width="800">
</p>

<details>
<summary>课程与证据</summary>
<img src="https://raw.githubusercontent.com/AGI-is-going-to-arrive/ahadiff/main/docs/video/public/screenshots/zh/zh-lesson.png" alt="带来源证据链接的课程" width="800">
<img src="https://raw.githubusercontent.com/AGI-is-going-to-arrive/ahadiff/main/docs/video/public/screenshots/zh/zh-diff.png" alt="带声明高亮的差异视图" width="800">
</details>

<details>
<summary>测验与复习</summary>
<img src="https://raw.githubusercontent.com/AGI-is-going-to-arrive/ahadiff/main/docs/video/public/screenshots/zh/zh-quiz.png" alt="根据课程生成的测验题" width="800">
<img src="https://raw.githubusercontent.com/AGI-is-going-to-arrive/ahadiff/main/docs/video/public/screenshots/zh/zh-review.png" alt="间隔复习卡片" width="800">
</details>

## 从源码安装

源码安装还需要 [uv](https://docs.astral.sh/uv/) 和 pnpm：

```bash
git clone https://github.com/AGI-is-going-to-arrive/ahadiff.git
cd ahadiff
uv sync --locked --dev
pnpm --dir viewer install --frozen-lockfile
pnpm --dir viewer build
uv tool install --editable .
```

## 致谢与许可

AhaDiff 参考了 karpathy/autoresearch、alchaincyf/darwin-skill、Evol-ai/SkillCompass、ZJU-REAL/SkillZero、safishamsi/graphify 和 karpathy/llm-wiki 的思路。感谢 [linux.do](https://linux.do/) 社区的反馈。

[MIT 许可证](https://github.com/AGI-is-going-to-arrive/ahadiff/blob/main/LICENSE)
