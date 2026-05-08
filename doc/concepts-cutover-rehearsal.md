# Concepts JSONL 到 SQLite 切换演练

这份演练只覆盖 derived concepts cache 的切换流程：从
`.ahadiff/review.sqlite` 导出或回滚 `.ahadiff/concepts.jsonl`，再用一致性校验确认两边没有漂移。

## 1. 前置条件

在目标仓库根目录运行：

```bash
test -f .ahadiff/review.sqlite
test -f .ahadiff/concepts.jsonl
uv run ahadiff concepts verify --repo-root .
```

这些命令注册在 `src/ahadiff/cli.py` 的 `_CONCEPTS_APP` 下。
`verify` 会调用 `src/ahadiff/wiki/concepts.py` 里的
`verify_concepts_consistency(db_path, jsonl_path)`。

## 2. 从 DB 导出 JSONL

```bash
uv run ahadiff concepts export --repo-root .
```

这个命令会走 `export_concepts_from_db(project_state_dir(root))`，
从 `.ahadiff/review.sqlite` 读 concepts rows，并原子覆盖 `.ahadiff/concepts.jsonl`。

## 3. 校验 DB 和 JSONL

```bash
uv run ahadiff concepts verify --repo-root .
```

期望输出：

```text
Consistent: JSONL and SQLite match.
```

如果两边不一致，命令会非零退出，并最多打印 20 条差异。

## 4. 回滚

先 dry run：

```bash
uv run ahadiff concepts rollback --repo-root . --dry-run
```

如果 dry run 显示需要用 SQLite 修复 JSONL，再执行：

```bash
uv run ahadiff concepts rollback --repo-root .
```

rollback 会在 repo write lock 保护下调用
`rollback_concepts_to_jsonl(db_path, jsonl_path)`，并原子写回 JSONL。

## 5. 回滚后复核

```bash
uv run ahadiff concepts verify --repo-root .
```

只有再次看到一致性通过，演练才算完成。
