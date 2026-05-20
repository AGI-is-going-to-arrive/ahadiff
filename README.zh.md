# 知返 AhaDiff

> **AI 写完，Diff 教回。**
>
> 把 AI 写出的每一个 git diff，变成带证据、能出题、会复习、还能推动质量变好的学习课程。

[English](./README.md) · [使用指南](./docs/USER_GUIDE.zh.html) · [中文视频教程](./docs/video/output/ahadiff-tutorial.zh.burned-subtitles.mp4) · [英文视频教程](./docs/video/output/ahadiff-tutorial.en.burned-subtitles.mp4)

---

## 这是什么

**知返 AhaDiff** 是一个 **local-first 的 AI Coding 学习层**。

它不是 PR 摘要，不是 repo wiki，也不是泛泛的“代码解释器”。它读取一次 git diff，把这次改动变成：

- 一篇讲清楚“改了什么、为什么改”的 **Lesson**
- 一份每条结论都能回到 `file:line` 的 **Claims 清单**
- 一套 **测验和复习流程**，让知识之后还能被召回
- 一条可比较的 **质量历史**，帮助你看到每次运行的变化

所有数据都存在每个 repo 自己的 `.ahadiff/` 里，`review.sqlite` 是唯一真相源。

> Code Wiki 解释一个仓库；知返 AhaDiff 解释这一次改动，而且每句话都要经得起 diff 证据校验。

## 为什么要做

AI 写代码越来越快，但人对“到底改了什么”的理解很容易掉队。知返要补上这个回路：

1. **AI 写完，理解要回到人身上** —— commit message 远远不够。
2. **每个解释都要有证据** —— 不接受幻觉函数，也不接受虚构因果。
3. **知识应该累积** —— 同一个概念被多次修改时，应该留下历史和 backlinks。
4. **质量应该可比较** —— 用稳定评分和 ratchet 取代“看起来还行”。

## 前置条件

- Python 3.11+
- git（需要在 PATH 中）
- [uv](https://docs.astral.sh/uv/)：可用 `curl -LsSf https://astral.sh/uv/install.sh | sh` 或 `brew install uv` 安装
- 一个 LLM provider：可以是带 API key 的远端服务（OpenAI / Anthropic / Gemini / Azure / 任意 OpenAI-compatible），也可以是本地服务（LM Studio / Ollama，不需要 key）

## 安装

AhaDiff 还没有发布到 PyPI。请从源码安装：
```bash
git clone https://github.com/agi-is-coming/ahadiff.git
cd ahadiff
uv tool install --editable .
ahadiff --version   # 应输出 ahadiff 1.1.0a0
```

## 配置 Provider

AhaDiff 需要 LLM 来生成课程。每个 repo 配置一次即可：
```bash
ahadiff init

# 注册并测试一个 provider（以 OpenAI 为例）
export OPENAI_API_KEY="sk-..."
ahadiff provider test \
  --name default \
  --provider-class openai \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY
```
`provider test` 会发送一个小探测请求。成功后，provider 配置自动写入 `.ahadiff/config.toml`。

支持的 provider class：`openai`、`openai_responses`、`gemini`、`anthropic`、`azure`、`newapi`、`lmstudio`、`ollama`。进阶的 OpenAI-compatible 或本地 provider 可以用 `providers.<name>.capability_overrides` 覆盖已知布尔能力，例如是否支持 native JSON schema；未知 key 或非布尔值会被拒绝。NewAPI 默认关闭 `supports_native_json_schema`；如果你的 NewAPI 网关后端真的支持 native JSON schema，可在 provider config 加 `capability_overrides = { supports_native_json_schema = true }`。更多细节见 [使用指南](./docs/USER_GUIDE.zh.html)。
> AhaDiff 默认使用 strict_local 隐私模式：除非你明确配置远端 provider，否则内容不会离开本机。

## 你的第一节课

```bash
# 学习最近一次 commit
ahadiff learn --last

# 打开本地 WebUI 阅读课程
ahadiff serve
```
在浏览器打开 http://localhost:8765。你会看到 Dashboard 里的第一次 run，然后可以继续进入 Lesson、Diff 和 Quiz。

还可以马上试试：
```bash
ahadiff quiz <run_id>    # 测测自己有没有看懂刚才的改动
ahadiff review           # 复习过去生成的卡片
```
9 种 diff 捕获方式、导出、概念图谱和进阶命令都在 [使用指南](./docs/USER_GUIDE.zh.html) 里。

## 功能

- **学习**：`ahadiff learn` 支持 9 种 diff 捕获模式：git commit、range、时间窗口（`--since`）、staged、unstaged、patch、patch URL、文件对比、目录对比。
- **证据化 Claims**：每条 lesson 结论都绑定 `file:line` 证据，并区分 verified、weak、not proven、contradicted、rejected 等状态。
- **结构化 LLM 输出**：生成链路会在支持时按 schema 约束 JSON 输出；默认使用 JSON object mode，并带 1 次有界 validation retry；原有 parser、repair 和 degraded 回退仍保留。截断或格式不完整的 fallback JSON 会触发重试，不会被直接接受。
- **测验与复习**：`ahadiff quiz` 用来测试刚学过的 run；`ahadiff review` 用间隔重复带回旧卡片。题量默认固定，也可以按 diff 大小自动调整。
- **评分**：每次 run 都会得到 8 维评分；配置后也可以启用 LLM judge。Diff Coverage 只看可见 `line_map.json` 里的文件和按行数加权的 hunk；hard gate 详情会写明本次 run 使用的自适应 claim-anchor 阈值。
- **WebUI**：`ahadiff serve` 打开 Dashboard、Lesson、Diff、Quiz、Review、Concepts、Run Detail、Settings 和 Guide。
- **导出**：支持 TSV / JSON、Anki `.apkg`，以及本地静态预览包。
- **概念图谱**：自动提取跨 diff 的概念关系，并用 Canvas 图谱和健康检查展示。
- **AI 工具集成**：为 Claude、Cursor、Copilot、Codex、Gemini、Aider 等工具写入项目级指引。
- **自动迭代**：`ahadiff improve` 在隔离 worktree 中优化 prompt，只保留更好的结果。
- **MCP Server**：只读 stdio MCP server，可供支持 MCP 的本地 agent 使用。
- **隐私**：三档模式：strict_local、redacted_remote、explicit_remote；默认 strict_local。
- **i18n**：CLI、WebUI 和 prompt 输出语言都支持中英文。
- **跨平台**：macOS、Linux、Windows，Python 3.11+。
- **安全**：URL secret 脱敏、provider URL 校验、输入校验、prompt 注入检测和安全门禁。

## 界面截图

<p align="center">
  <img src="./docs/video/public/screenshots/zh/zh-dashboard.png" alt="运行面板 — 运行记录、分数、棘轮轨迹" width="800">
</p>

<details>
<summary>课程 — AI 根据 diff 生成的教学课程</summary>
<img src="./docs/video/public/screenshots/zh/zh-lesson.png" alt="课程页面" width="800">
</details>

<details>
<summary>差异查看器 — 带 claim 关联的代码证据</summary>
<img src="./docs/video/public/screenshots/zh/zh-diff.png" alt="差异查看器" width="800">
</details>

<details>
<summary>测验 — 基于课程的主动回忆测试</summary>
<img src="./docs/video/public/screenshots/zh/zh-quiz.png" alt="测验页面" width="800">
</details>

<details>
<summary>复习 — 间隔重复卡片</summary>
<img src="./docs/video/public/screenshots/zh/zh-review.png" alt="复习页面" width="800">
</details>

<details>
<summary>概念图谱 — 跨 diff 的知识图谱</summary>
<img src="./docs/video/public/screenshots/zh/zh-concepts-graph.png" alt="概念图谱" width="800">
</details>

<details>
<summary>运行详情 — 分数与评估细节</summary>
<img src="./docs/video/public/screenshots/zh/zh-rundetail-overview.png" alt="运行详情概览" width="800">
</details>

<details>
<summary>设置 — Provider 与偏好配置</summary>
<img src="./docs/video/public/screenshots/zh/zh-settings.png" alt="设置页面" width="800">
</details>

## AI 工具集成

AhaDiff 会把项目级指引写入你的 AI 工具，让它知道这个 repo 的学习历史：
```bash
ahadiff install --detect        # 自动检测可用工具
ahadiff install claude     # 也支持: cursor, copilot, codex, gemini, aider, windsurf, cline, roo, continue, ...
```
当前支持 13 个目标。完整列表可运行 `ahadiff install --help`，也可以在 WebUI 的 Settings → AI Tool Guidance 中配置。

## 8 维评分 Rubric

| # | 维度 | 权重 | 硬门禁 |
|---|------|------|--------|
| 1 | Accuracy | 20 | < 14 → FAIL |
| 2 | Evidence | 18 | < 12 → FAIL |
| 3 | Diff Coverage | 14 | 自适应 claim-anchor 门禁。普通 diff 低于 7.70 会 FAIL；大而分散的 diff 阈值会降低，单/双文件但 hunk 很多的 diff 阈值会更严格。具体 ratio、regime 和 visible basis 会写进 hard gate detail。 |
| 4 | Learnability | 14 | — |
| 5 | Quiz Transfer | 10 | — |
| 6 | Spec Alignment | 10 | — |
| 7 | Conciseness | 8 | — |
| 8 | Safety & Privacy | 6 | 未缓解 Critical → FAIL |

三档 verdict：**PASS** ≥ 80 / **CAUTION** 60–80 / **FAIL** < 60。即使总分很高，hard gate 也可以直接让 run 变成 **FAIL**；contradicted claims 是 0 容忍，未缓解 Critical safety finding 也会 FAIL。

## 项目结构

```text
ahadiff/
├─ src/ahadiff/         # Python 源码
├─ viewer/              # React 19 前端
├─ tests/               # 测试套件
├─ prompts/             # LLM prompt 模板
├─ benchmarks/          # Eval benchmark fixtures
├─ docs/                # Landing page、使用指南、教程视频
├─ .github/workflows/   # CI/CD
├─ pyproject.toml       # Python 包配置
└─ LICENSE              # MIT
```

## 核心理念（N-文件契约）

AhaDiff 受 Karpathy / autoresearch 三文件契约启发，扩展成 N-文件变体：

| 文件 | 谁来改 | 作用 |
|------|--------|------|
| `program.md` | 人类 | 用自然语言描述 improve loop 的状态机 |
| evaluation bundle | **不可变** | `evaluator.py` + `rubric.py` + `rubric.yaml` + `gates.py` + `deterministic.py`，作为整体锁定 |
| `prompts/*.md` | Agent | improve loop 只允许改白名单里的生成 prompt；`eval_judge.md` 是评判 prompt 资源，不在可写集合里 |

循环：编辑 → commit → 评估 → 更好就保留，更差就回退 → 把结果记录下来，供之后复习和比较。

## 灵感来源、设计公理与 License

### 灵感来源

- **karpathy/autoresearch** —— N-文件契约和 git ratchet
- **alchaincyf/darwin-skill** —— 8 维 rubric 和 Phase 2.5 rewrite
- **Evol-ai/SkillCompass** —— PASS / CAUTION / FAIL 与 weakest-dimension-first
- **ZJU-REAL/SkillZero** —— helpfulness-driven retention 和 compact context
- **safishamsi/graphify** —— repo 级图谱 overlay
- **karpathy/llm-wiki** gist —— 持续积累的 wiki

### 设计公理

1. **Evidence first** —— 每条 claim 都必须能回到 `file:line`
2. **Learning over summary** —— 出题和复习比漂亮总结更重要
3. **Local-first trust** —— 隐私层级必须明确，本地优先是默认值
4. **Paper-like seriousness** —— 像认真论文，不像喧闹的 SaaS landing page
5. **One accent per style** —— 暖白纸感，加一个明确的 accent 色

### License

[MIT](./LICENSE)

---

> 知返 / AhaDiff —— Δ知 ↺
