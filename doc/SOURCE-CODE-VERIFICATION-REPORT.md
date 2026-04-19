# 灵感项目源码验证报告 — 基于实际代码的真相

> 验证时间：2026-04-19
> 方法：5 个并行 Agent 对 5 个 clone 到本地的项目进行深度代码分析
> 项目路径：`/Users/yangjunjie/Desktop/ahadiff-refs/`

---

## 总结：AhaDiff 方案需要的 12 处修订

| # | 修订项 | 严重度 | 当前状态 | 实际真相 |
|---|--------|--------|---------|---------|
| 1 | Phase 2.5 触发条件 | P0 | "连续2轮" | darwin-skill 原文："连续2个**skill**在round 1就break"，是 2 个 skill 不是 2 轮 |
| 2 | Phase 2.5 来源归因 | P0 | 部分归因于 autoresearch | autoresearch **完全没有** stuck 检测或 Phase 2.5，这是 darwin-skill 独有的 |
| 3 | results.tsv 格式 | P1 | 混用 5 列和 9 列 | autoresearch=5列, darwin-skill=9列, AhaDiff 应自行定义 |
| 4 | 三文件契约命名 | P1 | evaluator.py + generator_prompt.md | autoresearch 实际是 prepare.py + train.py，AhaDiff 的命名是改编不是复刻 |
| 5 | SkillCompass 维度数 | P0 | 暗示8维来自SC | SkillCompass 实际6维，且评估对象是 skill 文件质量，不是学习笔记质量 |
| 6 | PASS/CAUTION/FAIL 阈值 | P1 | 80/60 | SkillCompass 原版 70/50，AhaDiff 自行调高，需注明 |
| 7 | SKILL0 budget 递减方式 | P1 | "线性递减" | 实际是**阶段跳变** [6,3,0]，不是线性 |
| 8 | SKILL0 helpfulness 粒度 | P1 | "section helpfulness" | 实际是 skill file 级，但数据结构支持 section 级扩展 |
| 9 | keep/discard 实现 | P2 | 暗示有代码 | autoresearch 和 darwin-skill 都没有可执行判断代码，全在自然语言 |
| 10 | darwin-skill 子agent | P2 | 暗示有代码实现 | 纯 SKILL.md prompt 指令，零可执行代码 |
| 11 | Graphify graph.json 格式 | P2 | 未明确 | 标准 NetworkX node-link-data，有完整 Python API |
| 12 | 技术栈 litellm | ✅ 已修正 | 不用 LiteLLM | 正确 |

---

## 一、autoresearch — 真实架构

### 三文件契约的实际代码

| 文件 | 角色 | 关键内容 |
|------|------|---------|
| `program.md` | Agent 指令手册 | 纯 Markdown，定义实验规则（第 6-112 行）。**不是代码文件** |
| `prepare.py` | 不可变评估基础设施 | `evaluate_bpb()` (行343-365), `MAX_SEQ_LEN=2048`, `TIME_BUDGET=300`, `Tokenizer`, `make_dataloader()` |
| `train.py` | Agent 唯一可改文件 | GPT模型、优化器、超参数、训练循环（全部可改） |

### 关键发现

1. **results.tsv 是 5 列**：`commit | val_bpb | memory_gb | status | description`（Tab分隔）
2. **keep/discard 判断完全在自然语言中**（program.md 行103-104），无 Python 代码
3. **完全没有 Phase 2.5 或 stuck 检测**。program.md 行106 仅说"if you feel stuck, think harder"
4. **NEVER STOP 循环**：设计为无限运行，不询问用户
5. **简洁性准则**（行37）："0.001 提升 +20 行 hacky 代码不值得"
6. **val_bpb 无 hard gate**，仅有训练过程中的 NaN/爆炸检测

### AhaDiff 映射修正

```
autoresearch 真实映射          AhaDiff 应该用
─────────────────────────────────────────────────
program.md (Markdown 指令)  →  improve_program.md ✅ 正确
prepare.py (Python 评估器)  →  evaluator.py ✅ 概念正确，名称改编
train.py (Python 实验)      →  prompts/*.md ⚠️ 对象不同：autoresearch 改代码，AhaDiff 改 prompt
results.tsv (5列)           →  results.tsv ⚠️ AhaDiff 应自行定义列，不要照搬
Phase 2.5                   →  ❌ 不存在于 autoresearch，来源是 darwin-skill
```

---

## 二、darwin-skill — 真实架构

### 8 维 Rubric 完整定义

**SKILL.md 行27-64**:

| # | 维度 | 权重 | 评估标准（原文摘录） |
|---|------|------|---------|
| 1 | Frontmatter | 8 | name规范、description含触发词、<=1024字符 |
| 2 | Workflow | 15 | 步骤明确可执行、有序号、每步有输入/输出 |
| 3 | Boundaries | 10 | 异常处理、fallback路径、错误恢复 |
| 4 | Checkpoints | 7 | 关键决策前有用户确认 |
| 5 | Specificity | 15 | 不模糊、有具体参数/格式/示例 |
| 6 | Resources | 5 | references/scripts/assets引用正确 |
| 7 | Overall Architecture | 15 | 结构层次清晰、不冗余不遗漏 |
| 8 | Measured Performance | 25 | 用测试prompt跑一遍，输出质量是否符合 |

**计算规则**（行48-51）：`Total = SUM(维度分×权重) / 10`，满分100

### Phase 2.5 原文（行185-199）

> "当 hill-climbing **连续2个skill**都在 round 1 就 break（涨不动）时，提议一次「探索性重写」"

**关键澄清**：是"连续 2 个 skill"，不是"连续 2 轮"。含义：连续优化两个不同的 skill 时，每个 skill 都在第一轮就因分数没提升而终止。

**重写流程**：`git stash → 从头重写 → 评估 → 更好则采用，否则 git stash pop`

### 核心发现：零可执行代码

**darwin-skill 整个项目没有任何评分引擎、agent 编排器或优化循环的可执行实现。** 全部逻辑在 SKILL.md 自然语言指令中。实际代码仅有：
- `scripts/screenshot.mjs`（68行Playwright截图）
- `templates/*.html`（3个成果卡片模板）
- `docs/index.html`（说明页面）

---

## 三、SkillCompass — 真实架构

### 6 维评估体系（非8维）

**shared/scoring.md 行6-15**:

| ID | 维度 | 权重 | 评估对象 |
|----|------|------|---------|
| D1 | Structure | 10% | Frontmatter/Markdown格式/声明 |
| D2 | Trigger | 15% | 触发准确性/拒绝准确性/跨语言 |
| D3 | Security | **20%** | 8类安全检查（**唯一硬门禁**） |
| D4 | Functional | **30%** | 核心功能/边界处理/输出稳定性 |
| D5 | Comparative | 15% | With/Without skill 对比 |
| D6 | Uniqueness | 10% | 相似分析/差异分析/淘汰风险 |

### 真实阈值

| Verdict | 条件 | AhaDiff 声称 |
|---------|------|-------------|
| PASS | score >= **70** 且 D3 pass 且 D3 无 High | >= 80 |
| CAUTION | **50** <= score < **70**，或 D3 有 High | 60-80 |
| FAIL | score < **50** 或 D3 Critical | < 60 |

### 关键机制

1. **D3 Security 硬门禁**：任何 Critical → score=0, verdict=FAIL（`security-validator.js` 行46-49）
2. **Targeted Verification**：修复后不重跑全6维，只验证目标维度 + D3 + D4
3. **"One dimension per round"** 严格约束，唯一例外 D1+D2 可合并
4. **机械化打分**：D3 和 D5 通过查表计算，避免 LLM 主观抖动
5. **SkillCompass 评估的是 skill 文件质量，AhaDiff 评估的是学习笔记质量 — 评估对象完全不同**

---

## 四、Graphify — 真实架构

### graph.json Schema

**Node 字段**（`validate.py:6` + `export.py:288-290`）：
```json
{
  "id": "n_transformer",
  "label": "Transformer",
  "file_type": "code|document|paper|image|rationale",
  "source_file": "model.py",
  "source_location": "L42",
  "community": 0,
  "norm_label": "transformer"
}
```

**Edge 字段**（`validate.py:7` + `export.py:293-294`）：
```json
{
  "source": "n_transformer",
  "target": "n_attention",
  "relation": "contains|imports|calls|implements|referenced|semantically_similar_to",
  "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
  "confidence_score": 1.0,
  "source_file": "model.py",
  "weight": 1.0
}
```

### 集成接口

1. **Python API**：`from graphify import build_from_json, god_nodes, surprising_connections, cluster`
2. **MCP Server**：7 个 tool（query_graph, get_node, get_neighbors, get_community, god_nodes, graph_stats, shortest_path）
3. **graph.json 使用标准 NetworkX node-link-data 格式**，可直接用 `networkx.readwrite.json_graph.node_link_graph()` 加载

### AhaDiff 应添加的节点/边类型

节点：`Claim`, `Concept`, `Lesson`, `Quiz`, `ReviewCard`, `Run`
边：`modifies`, `reviewed_by`, `evidence_for`, `contradicts`, `teaches`

---

## 五、SKILL0/SkillZero — 真实架构

### Dynamic Curriculum 实现

**不是线性递减，是阶段跳变**。`curriculum_skill_manager.py` 行104-114：

```
max_set_schedule = [6, 3, 0]  # 三阶段
训练 180 步，test_freq=10:
  Step 1-60:   max_set=6（全部 skill）
  Step 61-120: max_set=3（保留 top-3）
  Step 121-180: max_set=0（完全撤架）
```

### Helpfulness 计算

`ray_trainer.py` 行1010-1056：
```
Delta_k = success_rate(with_skill) - success_rate(without_skill)
```

- 每 **10 步**评估一次（test_freq=10）
- **Skill file 级别**（如 `clean.md` 整体保留或移除）
- 数据结构已支持 section 级，但代码未实现

### AhaDiff 撤架映射

```
SkillZero 训练阶段           AhaDiff 学习阶段
─────────────────────────────────────────────
max_set=6 (全部skill)     →  lesson.full.md（完整解释）
max_set=3 (top-3 skill)   →  lesson.hint.md（关键提示）
max_set=0 (无skill)       →  quiz（纯主动回忆）
```

关键差异：SkillZero 通过 RL 更新模型权重实现内化，AhaDiff 通过重复练习+quiz 实现认知内化。

---

## 六、方案修订建议

### 必须修订（P0）

1. **Phase 2.5 归因**：从"借鉴 autoresearch"改为"借鉴 darwin-skill"。autoresearch 没有任何 stuck 检测
2. **Phase 2.5 触发描述**：从"连续2轮"改为"连续2个优化目标在首轮就无法改进"
3. **SkillCompass 维度归因**：明确声明"AhaDiff 的 8 维是自研体系，SkillCompass 原版 6 维且评估对象不同（skill 文件质量 vs 学习笔记质量）"

### 应该修订（P1）

4. **results.tsv 格式**：AhaDiff 应自行定义列，建议合并：`timestamp | run_id | head_sha | prompt_version | rubric_version | overall | verdict | status | weakest_dimension | note`（10列）
5. **三文件契约描述**：注明"AhaDiff 的 evaluator.py/generator_prompt.md 是对 autoresearch prepare.py/train.py 的概念改编，不是直接复刻"
6. **SKILL0 budget 描述**：从"线性递减"改为"阶段跳变"，并注明实际 schedule 是 [6,3,0]
7. **SKILL0 helpfulness 描述**：注明"原论文 skill file 级，AhaDiff 自行扩展到 section 粒度"
8. **PASS/CAUTION/FAIL 阈值**：注明"SkillCompass 原版 70/50，AhaDiff 调高为 80/60"

### 可选修订（P2）

9. **Graphify 集成**：方案中补充具体的 graph.json schema 和 Python API 导入路径
10. **机械化打分**：借鉴 SkillCompass D3 的查表打分，对 evidence/safety_privacy 维度采用确定性计算
11. **Targeted Verification**：借鉴 SkillCompass 的定向验证，improve loop 不重跑全8维

### 新增可借鉴机制

12. **autoresearch 简洁性准则**（program.md 行37）→ 可写入 AhaDiff 的 improve_program.md
13. **SkillCompass D3 机械化打分** → 可应用到 AhaDiff 的 safety_privacy 和 evidence 维度
14. **SkillCompass Targeted Verification** → improve loop 只验证目标维度 + safety + evidence
15. **darwin-skill 降级方案** → AhaDiff 的 dry_run 模式（无法跑 LLM 时退化为确定性检查）
16. **Graphify Python API** → `ahadiff graph import` 可直接 `from graphify import build_from_json`
