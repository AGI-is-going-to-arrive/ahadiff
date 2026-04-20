# 知返 AhaDiff 最终方案 · 多维度综合评估报告

> 评估时间：2026-04-19
> 评估方法：Claude Opus 4.6 主导 + 4 个并行 Agent 交叉验证
> 覆盖范围：方案文档(51KB) + UI 原型(53K tokens) + 4 个灵感项目源码验证 + 全网趋势调研

---

## 一、总体判定

| 维度 | 评分 | 判定 |
|------|------|------|
| 方案可行性 | **9.0/10** | 高度可行，个人开发者可执行 |
| 方案正确性 | **8.5/10** | 核心正确，部分项目引用有偏差（详见§三） |
| UI 原型质量 | **8.7/10** | 非常完善，可直接作为开发基准 |
| 市场定位独特性 | **9.5/10** | 全网无直接竞品 |
| MVP 可达性 | **8.0/10** | 3-5 天 CLI + viewer 可跑通 |

**结论：方案整体设计优秀，是一个罕见的「核心概念独特 + 技术可行 + 个人可执行 + 市场空白」的项目。建议立即进入开发。**

---

## 二、方案可行性评估

### 2.1 架构设计 ✅ 正确

- **Local-first CLI + 静态 HTML Viewer** 是最优 MVP 路径。不用 Next.js/React 的决定非常正确，Jinja 模板 + 嵌入 JSON 完全够用
- **Python 技术栈**（typer/rich/pydantic/jinja2/httpx）依赖轻量，无需 Node 构建链
- **九段开发顺序**设计合理，每段都有明确验收标准
- **不用 LiteLLM** 的决定正确且有安全依据（2026-03 供应链事件）

### 2.2 核心护城河 ✅ 独特

**Claim Verifier（声明验证器）** 是真正差异化：
- `diff → claims → evidence verification → lesson → quiz → review`
- 这比 `diff → explanation` 深了整整两层
- 四种状态（verified/weak/not_proven/rejected_contradicted）在全网无人做到
- negative evidence scan（反向证据扫描）是杀手级特性

### 2.3 风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| LLM claim extraction 质量不稳定 | 中 | deterministic verifier 前置 + VCR 回放测试 |
| 本地 Ollama 模型能力不足 | 中 | BYOK 云端模型作为可选路径 |
| "Aha!" 商标邻近风险 | 低 | 发布前做基础检索（方案已提到） |
| 单人维护瓶颈 | 中 | Agent Skill 安装体系降低用户摩擦 |

### 2.4 包名可用性 ✅

- **PyPI**: `ahadiff` 未被注册，可立即占位
- **npm**: `ahadiff` 未被注册
- **GitHub**: 已在使用中
- **建议**：立即用 `pip install twine && twine upload` 占位 PyPI

---

## 三、灵感项目真实性验证（关键发现）

### 3.1 Karpathy/autoresearch ✅ 准确借鉴

| AhaDiff 声明 | 真实情况 | 判定 |
|-------------|---------|------|
| 三文件契约：program.md + evaluator.py + generator_prompt.md | autoresearch 原版是 `program.md` + `prepare.py`(immutable) + `train.py`(mutable) | **准确** — 方案 §14.1 明确展示了映射关系，是有意的概念改编而非错误引用 |
| results.tsv 记录每次尝试 | 真实存在，记录 keep/discard/crash | **准确** |
| 单指标优化（val_bpb） | 真实，agent 的唯一目标是降低 val_bpb | **准确** |
| keep/discard/git ratchet | 真实，改进 git commit，退步 git reset | **准确** |

**评价**：autoresearch 的借鉴是最诚实、最深入的。方案完整理解了其设计哲学，并做了合理的领域迁移。

### 3.2 alchaincyf/darwin-skill ✅ 大部分准确

| AhaDiff 声明 | 真实情况 | 判定 |
|-------------|---------|------|
| 8 维 rubric | 确实是 8 维：Frontmatter(8), Workflow(15), Boundaries(10), Checkpoints(7), Specificity(15), Resources(5), Overall Architecture(15), Measured Performance(25) | **准确** |
| 100 分制 = 结构 60 + 效果 40 | 完全匹配 | **准确** |
| Phase 2.5 探索性重写 | 机制真实存在 | **准确** |
| 连续 3 轮卡住触发 Phase 2.5 | ⚠️ 实际触发条件是**连续 2 个 skill 未改进**，不是 3 轮 | **部分准确** |
| 子 agent 对照评测 | 确实使用 `with_skill` vs `baseline` 独立子 agent 对比 | **准确** |

**需修正**：将方案中的"连续 3 轮卡住"改为"连续 2 轮卡住"（或保持 3 作为 AhaDiff 自身参数，但需注明与 darwin-skill 原版不同）。

### 3.3 Evol-ai/SkillCompass ⚠️ 部分准确

| AhaDiff 声明 | 真实情况 | 判定 |
|-------------|---------|------|
| PASS / CAUTION / FAIL 三档 | 确实存在 | **准确** |
| weakest-dimension-first | 确实使用该策略 | **准确** |
| 分数阈值 80/60 | ⚠️ SkillCompass 原版阈值是 **70/50**，AhaDiff 自行调高了 | **部分准确**（功能性改编，非错误） |
| 8 维评分 | ⚠️ SkillCompass 实际是 **6 维**：Structure(10%), Trigger(15%), Security(20%), Functional(30%), Comparative(15%), Uniqueness(10%) | **不准确** — AhaDiff 的 8 维是自己设计的，不应归因于 SkillCompass |

**需修正**：
- 前端设计手册 §2.4 应注明"AhaDiff 自行设计了 8 维评分体系，借鉴了 SkillCompass 的 PASS/CAUTION/FAIL 三档判定和 weakest-dimension-first 策略"
- 不应暗示 SkillCompass 有 8 维

### 3.4 SKILL0 (ZJU-REAL, arXiv:2604.02268) ✅ 准确借鉴

| AhaDiff 声明 | 真实情况 | 判定 |
|-------------|---------|------|
| 学习撤架（progressive scaffolding removal） | 论文核心机制：从 full skill context 开始，逐步撤除 | **准确** |
| section helpfulness 评分 | ⚠️ 论文中是 **skill file-level helpfulness**（Δk 量化），不是 section 级 | **部分准确** |
| Dynamic Curriculum 机制 | 真实存在：Filter → Rank → Select，线性递减 budget | **准确** |
| 每步上下文 <0.5k tokens | 论文确认 | **准确** |

**评价**：方案 §13 对 SKILL0 的引用非常诚实，明确写了"AhaDiff 不做模型训练，所以不能 claim 实现 SKILL0 RL；它应该借的是撤脚手架学习法"。这种自觉性很好。

### 3.5 Graphify (safishamsi/graphify) ✅ 准确

- 真实存在的开源项目，30K+ stars（2026-04）
- 确实是 repo-level knowledge graph 工具
- 输出 `graphify-out/GRAPH_REPORT.md` + `graph.json` + 交互式 HTML
- AhaDiff 定位为 diff-level learning overlay 与 Graphify 互补而非竞争

### 3.6 Karpathy LLM Wiki Gist ✅ 准确

- 真实存在：2026 年 4 月 Karpathy 发布的 GitHub Gist
- 核心思想：增量积累 wiki，不重复 RAG
- AhaDiff 的 `index.md` + `concepts.jsonl` + `learning-signal.jsonl` 正是这一思想的落地

---

## 四、UI 原型评估（AhaDiff Warm v6.html）

> 基于 Playwright 自动化测试，15 张截图，全部 11 页面逐一验证

### 4.1 评分总览

| 维度 | 分数 | 说明 |
|------|------|------|
| 布局与视觉设计 | **9/10** | 暖白纸感、赤陶色系、Clay 标签、衬线/无衬线层级分明 |
| 交互质量 | **8.5/10** | 页面导航流畅、面包屑自动更新、20处 hover 效果 |
| 排版与色彩 | **9/10** | 中文行高 1.75、苹方+Noto Sans SC fallback、代码等宽字体 |
| 响应式设计 | **7.5/10** | ⚠️ 768px 平板视口布局断裂、移动端侧边栏缺背景遮罩 |
| 内容完整度 | **9.5/10** | 11 页面全部实现，claim 四种状态完整展示，mock 数据丰富 |

### 4.2 需修复的问题

1. **[P1] 平板响应式断裂**：768px 视口下侧边栏与内容区重叠，需添加断点
2. **[P2] 移动端侧边栏遮罩**：缺少 backdrop overlay，点击外部不关闭
3. **[P3] Rubric 进度条颜色区分**：8 维进度条颜色过于接近，难以快速识别弱项
4. **[P4] favicon 404**：缺少 favicon.ico（唯一的 console error）

### 4.3 判定

**UI 原型已经非常完善，可以直接作为 Jinja 模板转换的视觉基准。** 排版正确好看，交互完整。仅需修复平板响应式即可。

---

## 五、市场趋势与竞品分析

> 详见 `doc/trending-ai-projects-research-2026.md`

### 5.1 关键发现

- **全网无直接竞品**：没有任何项目做「从 AI diff 中学习 + 证据链验证」
- 最近的邻居是 wong2/diffx（diff 审查，85 star）和 backnotprop/plannotator（diff 标注，4K star），但都不做学习闭环
- **vibe coding 焦虑正在成为共识**：nuwa-skill (12.6K star) 证明「思维蒸馏」概念有市场
- **发布时机极佳**：AI agent + local-first 是 2026 Q1-Q2 绝对主流

### 5.2 AhaDiff 的独特定位

```
Code Wiki 解释仓库 → DeepWiki/Google Code Wiki 已做
PR summary → What The Diff 已做
Diff viewer → Diffity 已做
Diff 中学习 + 证据验证 → 没人做 ← AhaDiff 在这里
```

---

## 六、综合建议

### 6.1 立即行动项

1. ✅ **占位 PyPI**：`ahadiff` 名称可用，立即注册
2. ✅ **修正文档**：Phase 2.5 阈值改为 2（或注明 AhaDiff 自定义为 3），SkillCompass 维度数改为 6
3. ✅ **修复 UI**：平板响应式断点 + 侧边栏遮罩
4. ✅ **开始第一段开发**：`ahadiff init` + `ahadiff learn --dry-run`

### 6.2 关于 Graphify/LLM Wiki 是否需要 clone

| 项目 | 建议 | 原因 |
|------|------|------|
| **Graphify** | ✅ **建议 clone + 运行** | 需要理解 `graph.json` 的实际 schema 才能写好 `graphify_import.py`；需要知道 `GRAPH_REPORT.md` 的真实结构 |
| **LLM Wiki** | ❌ **不需要 clone** | 它只是一个 Gist（idea file），没有可运行的代码。直接读 gist 内容，理解增量 wiki 模式即可 |

具体操作建议：
```bash
# Graphify - 建议 clone
git clone https://github.com/safishamsi/graphify.git ../graphify
cd ../graphify && pip install -e . && graphify ../ahadiff
# 查看输出
cat graphify-out/GRAPH_REPORT.md
cat graphify-out/graph.json | python3 -m json.tool | head -100

# LLM Wiki - 只需读 gist
# https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
# 核心模式已在方案 index.md + concepts.jsonl 中落地，无需额外操作
```

### 6.3 不需要的项目

- **autoresearch**：不需要 clone。它是 GPU 训练项目（需要数据集+GPU），AhaDiff 只借鉴了它的三文件契约和 ratchet 模式，这些概念已完整理解
- **darwin-skill**：不需要 clone。它是 Claude Skill 优化器，AhaDiff 已吸收其 rubric 评分和 improve loop 思想
- **SkillCompass**：不需要 clone。已验证其 PASS/CAUTION/FAIL 体系，AhaDiff 已完成改编

### 6.4 长期演进建议

1. **v0.1**（3-5 天 MVP）：CLI + claim verifier + lesson.md + 本地 HTML
2. **v0.2**：quiz + review + score.json + ratchet
3. **v0.3**：Graphify 集成 + agent install
4. **v0.5**：improve loop + benchmark suite
5. **v1.0**：社区开源 + PyPI 发布

---

## 七、项目引用准确性汇总表

| 灵感项目 | 引用维度 | 准确性 | 需修正 |
|---------|---------|--------|--------|
| autoresearch | 三文件契约 | ✅ 准确 | 无 |
| autoresearch | ratchet/keep/discard | ✅ 准确 | 无 |
| darwin-skill | 8 维 rubric | ✅ 准确 | 无 |
| darwin-skill | Phase 2.5 阈值 | ⚠️ 部分准确 | 2 轮非 3 轮 |
| darwin-skill | 子 agent 对照 | ✅ 准确 | 无 |
| SkillCompass | PASS/CAUTION/FAIL | ✅ 准确 | 无 |
| SkillCompass | 维度数 | ❌ 不准确 | 原版 6 维非 8 维 |
| SkillCompass | 分数阈值 | ⚠️ 改编 | 原版 70/50，AhaDiff 用 80/60 |
| SKILL0 | 撤架学习 | ✅ 准确 | 无 |
| SKILL0 | section helpfulness | ⚠️ 部分准确 | 原版是 skill file 级非 section 级 |
| Graphify | repo-level map | ✅ 准确 | 无 |
| LLM Wiki | 增量 wiki | ✅ 准确 | 无 |

---

*报告生成于 2026-04-19 · Claude Opus 4.6 + 4 个并行 Agent 交叉验证*
*UI 评估详见 `eval-screenshots/EVALUATION-REPORT.md` · 趋势调研详见 `doc/trending-ai-projects-research-2026.md`*
