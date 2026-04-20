# 借鉴点源码验证报告

> 验证日期：2026-04-20
> 验证范围：决策表 #6, #11, #13, #19, #23 共 5 条借鉴点
> 验证方法：逐行读取源码，与决策文档声明逐字对比

---

## #6 — redirect stdout 到 run.log

**决策文档声明**：redirect stdout > run.log

**源码实际内容** (`repo/autoresearch/program.md` line 99):

```
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
```

**验证结论：准确，但有细微差异**

| 维度 | 决策文档 | 源码实际 |
|------|---------|---------|
| 重定向方式 | `redirect stdout` | `> run.log 2>&1`（stdout + stderr 全重定向） |
| tee 禁止 | 未提及 | **明确禁止**: "do NOT use tee" |
| 禁止原因 | "降低终端噪音" | "do NOT ... let output flood your context"（防止上下文溢出） |
| 结果读取 | 未提及 | `grep "^val_bpb:\|^peak_vram_mb:" run.log`（结构化提取） |

**AhaDiff 适配关注点**:
1. 决策文档只说 "redirect stdout"，实际是 stdout+stderr 全部重定向 (`2>&1`)。AhaDiff 的 run.log 也应该捕获 stderr，否则 LLM 调用错误日志会丢失。
2. autoresearch 禁止 tee 的核心原因是**防止 LLM agent 上下文窗口被输出淹没**，而非简单的"终端噪音"。AhaDiff 作为 CLI 工具给人用，可以考虑 tee 到终端同时写 log（与 autoresearch 的 agent 场景不同）。
3. autoresearch 用 grep + `^key:` 前缀从日志中提取结构化数据。AhaDiff 的 `^wiki_score:` 协议（HC-10）与此一致。

---

## #11 — 异常处理决策表（9 场景）

**决策文档声明**：异常处理决策表（9 场景）

**源码实际内容** (`repo/darwin-skill/SKILL.md` lines 270-286):

逐行列举实际场景：

| # | 场景 | 触发条件 | 处理动作 |
|---|------|---------|---------|
| 1 | 不在 git 仓库 | `git rev-parse` 失败 | 提示 git init / cp 备份 |
| 2 | results.tsv 缺失 | 文件不存在 | 新建+写表头行（9列含eval_mode） |
| 3 | results.tsv 损坏 | 列数不匹配/非TSV | 备份后重建 |
| 4 | 分支已存在 | `git checkout -b` 失败 | 分支名加 `-2`/`-3` |
| 5 | `git revert` 失败 | 冲突/工作树脏 | git stash + 重试 / 手动恢复 |
| 6 | MAX_ROUNDS 触顶 | 已跑3轮仍有短板 | 三选一：加1轮/Phase 2.5/收工 |
| 7 | 优化后超150%体积 | 新文件 > 原 × 1.5 | 拒绝提交，回到精简 |
| 8 | test-prompts.json 已存在 | 文件已在 skill 目录 | 复用/重写/追加三选一 |
| 9 | SKILL.md 找不到 | 目录存在但无 SKILL.md | 终止+记 status=error |
| 10 | 分数计算规则 | 浮点精度漂移 | 总分保留1位小数，严格 `>` |

**验证结论：不准确 — 实际是 10 个场景，非 9 个**

决策文档说"9 场景"，但源码表格有 **10 行**。第 10 行"分数计算规则/浮点精度漂移"是独立的边界条件场景。

**AhaDiff 适用性分析**:

| 场景 | AhaDiff 适用 | 备注 |
|------|:---:|------|
| 1 不在 git 仓库 | 是 | AhaDiff 依赖 git diff，此场景必须处理 |
| 2 results.tsv 缺失 | 是 | 直接映射到 AhaDiff 的 results.tsv（但列数是 10 非 9） |
| 3 results.tsv 损坏 | 是 | 备份+重建策略可直接复用 |
| 4 分支已存在 | 部分 | AhaDiff improve loop 在分支上操作，需要 |
| 5 git revert 失败 | 是 | ratchet 回滚是核心路径 |
| 6 MAX_ROUNDS 触顶 | 是 | 映射到 `--rounds N` 参数 |
| 7 超150%体积 | 延后 | 决策表已将 #10 延后到 v0.2+ |
| 8 test-prompts.json 已存在 | 否 | darwin-skill 特有，AhaDiff 无此文件 |
| 9 SKILL.md 找不到 | 否 | darwin-skill 特有 |
| 10 浮点精度 | 是 | 8维加权计算必须处理精度问题 |

**结论**: 10 个场景中约 6-7 个直接适用于 AhaDiff，#8 和 #9 是 darwin-skill 特有场景。

---

## #13 — eval-result.json Schema

**决策文档声明**：score/max/details/sub_scores/issues/metadata/verdict 字段

**源码实际内容** (`repo/SkillCompass/schemas/eval-result.json`):

### 顶层字段（实际）:

```json
"required": ["skill_name", "skill_path", "skill_type", "scores", "overall_score", "verdict", "weakest_dimension", "recommendations", "metadata"]
```

### 每个维度评分对象的字段（以 structure 为例）:

```json
"required": ["score", "max", "details", "sub_scores", "issues"]
```

**验证结论：基本准确，但有层级混淆**

| 决策文档列出的字段 | 实际位置 | 是否存在 |
|---|---|:---:|
| score | `scores.<dim>.score` | 是 |
| max | `scores.<dim>.max` | 是 |
| details | `scores.<dim>.details` | 是 |
| sub_scores | `scores.<dim>.sub_scores` | 是 |
| issues | `scores.<dim>.issues` | 是 |
| metadata | 顶层 `metadata` + 各维度内 `metadata` | 是（双层） |
| verdict | 顶层 `verdict` | 是 |

**决策文档未提及的重要字段**:

| 字段 | 位置 | 意义 |
|------|------|------|
| `skill_name` | 顶层 required | 技能标识 |
| `skill_path` | 顶层 required | 文件路径 |
| `skill_type` | 顶层 required, enum: atom/composite/meta | 类型分类 |
| `partial` | 顶层 optional | 是否部分评估 |
| `overall_score` | 顶层 required, 0-100 | 总分 |
| `weakest_dimension` | 顶层 required | 最弱维度标识 |
| `recommendations` | 顶层 required | 改进建议数组 |
| `action` | 顶层 optional | 推荐动作（evolve/quick_fix/rollback/merge/rebuild/remove） |

**Schema 与 AhaDiff 8 维 rubric 映射**:

SkillCompass 是 **6 维**（structure/trigger/security/functional/comparative/uniqueness），评估 SKILL.md 文件质量。AhaDiff 是自研 **8 维**（accuracy/evidence/diff_coverage/learnability/quiz_transfer/spec_alignment/conciseness/safety_privacy），评估学习笔记质量。

可借鉴的 Schema 结构模式:
1. `score + max + details + sub_scores + issues` 五元组 — 直接复用到 AhaDiff 的每个维度
2. 顶层 `verdict` enum (PASS/CAUTION/FAIL) — 直接复用
3. `weakest_dimension` 字段 — 支持 weakest-first 优化策略
4. `action` 推荐动作 — AhaDiff 可映射为 keep/rewrite/rollback
5. `partial` 标记 — AhaDiff 可用于 degraded run 场景

**注意**: security 维度的 required 字段是 `["score", "max", "pass", "findings", "tools_used"]`，与其他维度不同（没有 sub_scores/issues，有 pass/findings/tools_used）。AhaDiff 的 safety_privacy 维度可参考此差异化设计。

---

## #19 — Tier 分类 + Few-shot + 算术验证行

**决策文档声明**：Tier A/B/C 分类；算术验证行如 "Score check: 9×0.30 + 8×0.20 = 8.25 → 8"

**源码实际内容** (`repo/SkillCompass/prompts/d4-functional.md`):

### Tier 分类 (lines 34-42):

```markdown
## Step 1: Tier Classification
| Tier | Output Type | Examples | Evaluation Approach |
| A | Verifiable output | Code generators, data transforms | Assertion-based |
| B | Creative/advisory | Guidance, recommendations, reviews | Rubric-based |
| C | Behavior modification | Context rules, persona, constraints | Before/after |
```

### 算术验证行 (line 114):

```
Verify: for sub-scores [8, 7, 7, 6, 5, 8]: 8×0.30 + 7×0.20 + 7×0.15 + 6×0.15 + 5×0.10 + 8×0.10 = 2.4 + 1.4 + 1.05 + 0.9 + 0.5 + 0.8 = 7.05 → 7
```

### Few-shot 示例 (lines 159-401):

共 **5 个** few-shot 示例：

| 示例 | Tier | Score | 主题 |
|------|------|-------|------|
| A | Tier A | 8 | json-schema-generator（规范 atom skill） |
| B | Tier B | 4 | code-reviewer（模糊 advisory skill） |
| C | Tier C | 6 | security-mindset（行为修改 skill） |
| D | Tier A | 9 | gcalcli-calendar（工具集成 skill） |
| E | Tier B | 2 | devops（极简 stub skill） |

### 每个 few-shot 末尾都有 Score check 行:

```
Example A: Score check: 9×0.30 + 8×0.20 + 9×0.15 + 8×0.15 + 5×0.10 + 9×0.10 = 2.7 + 1.6 + 1.35 + 1.2 + 0.5 + 0.9 = 8.25 → 8 ✓
Example B: Score check: 4×0.30 + 2×0.20 + 3×0.15 + 4×0.15 + 2×0.10 + 5×0.10 = 1.2 + 0.4 + 0.45 + 0.6 + 0.2 + 0.5 = 3.35 → round(3.35) = 3
Example C: Score check: 7×0.30 + 5×0.20 + 6×0.15 + 6×0.15 + 4×0.10 + 7×0.10 = 2.1 + 1.0 + 0.9 + 0.9 + 0.4 + 0.7 = 6.0 → 6 ✓
Example D: Score check: 10×0.30 + 9×0.20 + 9×0.15 + 9×0.15 + 8×0.10 + 9×0.10 = 3.0 + 1.8 + 1.35 + 1.35 + 0.8 + 0.9 = 9.2 → 9 ✓
Example E: Score check: 2×0.30 + 1×0.20 + 2×0.15 + 2×0.15 + 1×0.10 + 3×0.10 = 0.6 + 0.2 + 0.3 + 0.3 + 0.1 + 0.3 = 1.8 → 2 ✓
```

**验证结论：准确**

决策文档的声明完全匹配。Tier A/B/C 分类存在，算术验证行存在且格式与引用一致。

**额外发现 — 决策文档未提及的重要细节**:

1. **6 个子评分维度 + 权重**: core_functionality(30%), edge_handling(20%), output_stability(15%), output_quality(15%), error_handling(10%), instruction_clarity(10%)
2. **每个维度有 5 级评分指南** (0-2, 3-4, 5-6, 7-8, 9-10)，锚定评分标准
3. **Step 3: Mental Test Cases** — 要求生成 3-5 个思维测试用例，不执行但记录在 metadata
4. **Example B 的 Score check 有误**: 计算结果 3.35 → 标注为 3，但 JSON 输出中 score 是 4（不一致）。这说明算术验证行本身也可能出错，AhaDiff 应在代码层面做算术校验而非仅靠 LLM 自检。

**AhaDiff 适配**:
- AhaDiff 有 8 个维度（非 6 个），权重不同，需要重新设计 few-shot 示例
- 算术验证行公式需适配为 8 维版本
- 建议增加代码侧的 `assert abs(computed - declared) < 0.5` 校验，不完全信任 LLM 自算

---

## #23 — SHA256 内容寻址缓存

**决策文档声明**：`hash = content + '\x00' + path`

**源码实际内容** (`repo/graphify/graphify/cache.py` lines 20-41):

```python
def file_hash(path: Path, root: Path = Path(".")) -> str:
    """SHA256 of file contents + path relative to root."""
    p = Path(path)
    raw = p.read_bytes()
    content = _body_content(raw) if p.suffix.lower() == ".md" else raw
    h = hashlib.sha256()
    h.update(content)
    h.update(b"\x00")
    try:
        rel = p.resolve().relative_to(Path(root).resolve())
        h.update(str(rel).encode())
    except ValueError:
        h.update(str(p.resolve()).encode())
    return h.hexdigest()
```

**验证结论：基本准确，但有 3 个重要细节被遗漏**

| 维度 | 决策文档 | 源码实际 |
|------|---------|---------|
| 基本公式 | `hash = content + '\x00' + path` | `SHA256(content + \x00 + relative_path)` — 基本一致 |
| 路径类型 | "path" | **相对路径**（相对于 root），非绝对路径；目的是跨机器/CI 可移植 |
| Markdown 特殊处理 | 未提及 | `.md` 文件**剥离 YAML frontmatter**，仅 hash body 内容 |
| fallback | 未提及 | 文件在 root 外时 fallback 到**绝对路径** |

### 完整 cache 实现细节:

1. **Cache key**: `SHA256(body_content + \x00 + relative_path).hexdigest()`
2. **Cache 存储路径**: `graphify-out/cache/{hash}.json`
3. **Cache value**: `{"nodes": [...], "edges": [...], "hyperedges": [...]}`
4. **写入策略**: 原子写入（先写 `.tmp`，再 `os.replace`），Windows 有 `shutil.copy2` fallback
5. **Frontmatter 剥离** (`_body_content`): 如果 `.md` 文件以 `---` 开头，找到第二个 `\n---` 后取其之后的内容

**AhaDiff 适配关注点**:

1. **Markdown frontmatter 剥离**: graphify 这样做是为了让 metadata 变更不影响缓存。AhaDiff 缓存的是 diff + LLM 输出，不需要此逻辑。但如果缓存 lesson 文件（有 frontmatter），需要决定是否剥离。
2. **相对路径**: graphify 用相对路径保证可移植性。AhaDiff 的 cache key 应该考虑加入 `redaction_config hash`（决策文档风险表已提到），因为相同文件+不同隐私配置 = 不同输出。
3. **\x00 分隔符**: 防止 content 尾部与 path 头部拼接产生碰撞。这是正确的做法，AhaDiff 应保留。
4. **建议的 AhaDiff cache key**: `SHA256(diff_content + \x00 + commit_sha + \x00 + redaction_config_hash + \x00 + prompt_version)`

---

## 总结

| # | 借鉴点 | 准确性 | 关键发现 |
|---|--------|:------:|---------|
| 6 | redirect stdout | 基本准确 | 实际是 stdout+stderr (`2>&1`)，tee 被明确禁止；AhaDiff 作为 CLI 工具可考虑 tee |
| 11 | 异常处理决策表 | **不准确** | 实际 **10** 个场景（非 9 个），第 10 个是浮点精度处理；6-7 个适用于 AhaDiff |
| 13 | eval-result.json Schema | 基本准确 | 字段都存在但有层级混淆；security 维度结构与其他不同；Schema 是 6 维非 8 维 |
| 19 | Tier+Few-shot+算术验证行 | **准确** | Tier A/B/C 存在，5 个 few-shot 示例，每个有 Score check 行；Example B 存在 score 不一致 bug |
| 23 | SHA256 cache | 基本准确 | 公式正确但遗漏：相对路径（非绝对）、.md frontmatter 剥离、root 外 fallback |

### 需要修正的决策文档内容

1. **#11**: "9 场景" → "10 场景"
2. **#6**: 补充说明是 stdout+stderr 全重定向，以及 tee 被明确禁止的上下文（agent context flooding）
3. **#23**: 补充 3 个遗漏细节（相对路径、frontmatter 剥离、fallback），以及 AhaDiff 需额外加入的 key 组成部分
