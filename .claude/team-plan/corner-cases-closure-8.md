# Corner Cases 工程闭合方案 (CC-NEW-1 ~ CC-NEW-8)

> 生成时间：2026-04-20
> 基于：ahadiff-v01-comprehensive-review-research.md + ahadiff-v01-stages-4-9.md

---

## CC-NEW-1: Locale Alias 漂移

**问题**: `zh_CN`/`zh-Hans`/`ZH-cn` 产生不同 cache/VCR key。

**文件**: `src/ahadiff/i18n/resolver.py`

**函数**: `normalize_locale(raw: str) -> Literal["en", "zh-CN"]`

```python
# src/ahadiff/i18n/resolver.py
import re

_LOCALE_MAP: dict[str, str] = {
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN",
    "zh_cn": "zh-CN", "zh_hans": "zh-CN", "zh-hans-cn": "zh-CN",
    "en": "en", "en-us": "en", "en_us": "en", "en-gb": "en",
}
_SUPPORTED: set[str] = {"en", "zh-CN"}

def normalize_locale(raw: str) -> str:
    """BCP47 归一化。未知 locale 降级为 en。"""
    key = re.sub(r"[_\s]", "-", raw.strip()).lower()
    resolved = _LOCALE_MAP.get(key)
    if resolved:
        return resolved
    # 尝试前缀匹配 (e.g. "zh-TW" → "zh-CN" for v0.1)
    prefix = key.split("-")[0]
    return _LOCALE_MAP.get(prefix, "en")
```

**调用点**: `config.py::resolve_effective_locale()` 在启动时调用一次，结果写入 `RunRecord.content_lang`，后续 cache key / VCR key 均读此字段。

**Schema 变更**: 无新增字段，`content_lang` 已在 RunRecord 中定义。

**测试用例** (`tests/unit/test_i18n_resolver.py`):
```python
@pytest.mark.parametrize("raw,expected", [
    ("zh_CN", "zh-CN"), ("zh-Hans", "zh-CN"), ("ZH-cn", "zh-CN"),
    ("zh-Hant", "zh-CN"),  # v0.1 不区分繁简
    ("en-US", "en"), ("EN_GB", "en"), ("fr", "en"),  # 未知降级
    ("", "en"), ("  zh_CN  ", "zh-CN"),
])
def test_normalize_locale(raw, expected):
    assert normalize_locale(raw) == expected
```

---

## CC-NEW-2: 模型忽略 OUTPUT_LANGUAGE 输出混合语言

**文件**: `src/ahadiff/llm/language_guard.py`

**函数**: `detect_output_language(text: str) -> str` + `enforce_language(text: str, expected: str, retry_fn) -> tuple[str, bool]`

**算法选择**: 正则首行检测（轻量、零依赖），不用 langdetect（安装重、短文本不准）。

```python
# src/ahadiff/llm/language_guard.py
import re

_CJK_RANGE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN_RANGE = re.compile(r"[a-zA-Z]")

def detect_output_language(text: str) -> str:
    """检测前 500 字符中 CJK vs Latin 比例。"""
    sample = text[:500]
    cjk_count = len(_CJK_RANGE.findall(sample))
    latin_count = len(_LATIN_RANGE.findall(sample))
    if cjk_count == 0 and latin_count == 0:
        return "unknown"
    ratio = cjk_count / (cjk_count + latin_count + 1e-9)
    if ratio > 0.3:
        return "zh-CN"
    elif ratio < 0.1:
        return "en"
    return "mixed"

def enforce_language(
    text: str, expected: str, retry_fn, max_retries: int = 1
) -> tuple[str, bool]:
    """
    检测语言，不匹配时重试一次。
    Returns: (final_text, was_retried)
    """
    detected = detect_output_language(text)
    if detected == expected or detected == "unknown":
        return text, False
    # mixed 或完全错误 → 重试
    for _ in range(max_retries):
        text = retry_fn()
        detected = detect_output_language(text)
        if detected == expected or detected == "unknown":
            return text, True
    # 重试失败，接受并标记
    return text, True
```

**重试策略**: 最多 1 次重试（在 prompt 前追加 `CRITICAL: You MUST output in {lang}. Previous attempt was rejected.`）。重试后仍不匹配则接受但标记。

**存储位置**: `RunRecord` 新增 `mixed_language_output: bool = False`（写入 review.sqlite `result_events.note_json`）。

**测试用例** (`tests/unit/test_language_guard.py`):
```python
def test_detect_chinese():
    assert detect_output_language("这是一段中文解释") == "zh-CN"

def test_detect_english():
    assert detect_output_language("This is an explanation") == "en"

def test_detect_mixed():
    # 30% 临界
    assert detect_output_language("abc中文def") == "mixed"

def test_enforce_retries_once(mocker):
    mock_retry = mocker.Mock(return_value="纯中文输出")
    text, retried = enforce_language("English output", "zh-CN", mock_retry)
    assert retried is True
    mock_retry.assert_called_once()
```

---

## CC-NEW-3: 脱敏后 Evidence Anchor 失去回链性

**文件**: `src/ahadiff/safety/redaction.py` + `src/ahadiff/claims/schemas.py`

**函数**: `assign_file_id(path: str) -> str` + `build_display_path(file_id: str, redaction_map: dict) -> str`

**file_id 生成策略**: 基于原始路径的确定性 hash（SHA-256 前 12 位 hex），脱敏前生成并持久化到 `redaction_map.json`。

```python
# src/ahadiff/safety/redaction.py
import hashlib

def assign_file_id(path: str) -> str:
    """生成确定性 file_id，脱敏前调用。"""
    return "f_" + hashlib.sha256(path.encode()).hexdigest()[:12]

def build_display_path(file_id: str, redaction_map: dict) -> str | None:
    """从 redaction_map 反查显示路径（可能部分脱敏）。"""
    entry = redaction_map.get(file_id)
    if not entry:
        return None
    return entry.get("display_path", f"[redacted:{file_id}]")
```

**display_path 转换规则**:
- 路径本身无敏感信息 → `display_path = 原始路径`
- 路径含敏感段（如 `/home/user/.secrets/config.py`）→ `display_path = "[redacted]/.secrets/config.py"`（只脱敏敏感前缀）

**Claim Schema 变更** (`src/ahadiff/claims/schemas.py`):
```python
class EvidenceAnchor(BaseModel):
    file_id: str          # 稳定标识，不因脱敏改变
    display_path: str     # 用户可见路径（可能部分脱敏）
    line_start: int
    line_end: int
    hunk_id: str | None = None
```

原有的 `file_path: str` 字段废弃，迁移为 `file_id` + `display_path` 二元组。

**redaction_map.json** 结构（每个 run 一份，写入 `runs/<run_id>/`）:

⚠️ **隐私模式条件写入**：`original_path` 字段仅在 `strict_local` 模式下写入（数据不离开本机）。`redacted_remote` 和 `explicit_remote` 模式下该字段为 `null`，防止敏感路径随 artifact 意外泄露。

```json
{
  "f_a1b2c3d4e5f6": {
    "original_path": "/home/user/project/src/auth.py",
    "original_path_note": "仅 strict_local 模式写入，其他模式为 null",
    "display_path": "src/auth.py",
    "redacted_segments": []
  }
}
```

**测试用例** (`tests/unit/test_redaction_anchor.py`):
```python
def test_file_id_deterministic():
    assert assign_file_id("src/main.py") == assign_file_id("src/main.py")

def test_file_id_different_paths():
    assert assign_file_id("a.py") != assign_file_id("b.py")

def test_display_path_normal():
    rmap = {"f_abc": {"display_path": "src/main.py"}}
    assert build_display_path("f_abc", rmap) == "src/main.py"

def test_display_path_missing():
    assert build_display_path("f_missing", {}) is None
```

---

## CC-NEW-4: 浏览器重试导致 Learning Signal 双写

**文件**: `src/ahadiff/serve/middleware.py` + `src/ahadiff/review/database.py`

**前端 Key 生成策略**: 客户端生成 `idempotency_key = crypto.randomUUID()`（浏览器原生 API），首次请求时生成并缓存在按钮的 `data-idem-key` 属性中，重试时复用。

```javascript
// viewer/static/app.js
function postSignal(url, payload) {
    const key = payload._idempotency_key || crypto.randomUUID();
    payload._idempotency_key = key;
    return fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Idempotency-Key": key},
        body: JSON.stringify(payload),
    });
}
```

**SQLite 索引定义** (`src/ahadiff/review/migrations/001_init.sql`):
```sql
CREATE TABLE IF NOT EXISTS learning_signals (
    event_id      TEXT PRIMARY KEY,  -- UUID v7
    idempotency_key TEXT NOT NULL,
    signal_type   TEXT NOT NULL,     -- 'mark_wrong' | 'quiz_answer' | 'srs_review' | 'helpfulness'
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(idempotency_key)          -- 幂等保证
);
CREATE INDEX idx_signals_type_time ON learning_signals(signal_type, created_at DESC);
```

**冲突处理** (`src/ahadiff/review/database.py`):
```python
def insert_learning_signal(self, idempotency_key: str, signal_type: str, payload: dict) -> str:
    """插入 learning signal，冲突时返回已有 event_id。"""
    event_id = uuid7_str()
    try:
        self.conn.execute(
            "INSERT INTO learning_signals (event_id, idempotency_key, signal_type, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (event_id, idempotency_key, signal_type, json.dumps(payload)),
        )
        self.conn.commit()
        return event_id
    except sqlite3.IntegrityError:
        # idempotency_key 冲突 → 返回原 event_id
        row = self.conn.execute(
            "SELECT event_id FROM learning_signals WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row[0]
```

**HTTP 响应**: 冲突时返回 `200 OK`（非 409），body 包含原 `event_id`，前端无感知。

**测试用例** (`tests/unit/test_idempotency.py`):
```python
def test_duplicate_signal_returns_same_id(db):
    id1 = db.insert_learning_signal("key-1", "mark_wrong", {"claim_id": "c01"})
    id2 = db.insert_learning_signal("key-1", "mark_wrong", {"claim_id": "c01"})
    assert id1 == id2

def test_different_keys_different_ids(db):
    id1 = db.insert_learning_signal("key-1", "mark_wrong", {"claim_id": "c01"})
    id2 = db.insert_learning_signal("key-2", "mark_wrong", {"claim_id": "c01"})
    assert id1 != id2
```

---

## CC-NEW-5: 同一概念多语言/格式被当多个节点

**文件**: `src/ahadiff/concepts/identity.py`

**函数**: `compute_term_key(term: str) -> str`

**term_key 生成算法**: Normalize → ASCII slug（不做 stemming，保留完整词义）。

```python
# src/ahadiff/concepts/identity.py
import re
import unicodedata

def compute_term_key(term: str) -> str:
    """
    稳定概念身份 key。
    规则: lowercase → NFD strip accents → 连续非 alnum 替换为 _ → strip 两端 _
    示例: "Dependency Injection" → "dependency_injection"
           "依赖注入" → "依赖注入" (CJK 保留原文)
           "DI (Dependency Injection)" → "di_dependency_injection"
    """
    text = term.strip().lower()
    # NFKD 正规化，去除组合标记（保留 CJK）
    normalized = unicodedata.normalize("NFKD", text)
    # 移除组合标记（变音符等），保留 CJK
    cleaned = "".join(
        c for c in normalized
        if not unicodedata.combining(c)
    )
    # 非字母数字（含 CJK）替换为 _
    slug = re.sub(r"[^\w]", "_", cleaned, flags=re.UNICODE)
    # 压缩连续 _
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug
```

**aliases 匹配规则** (`src/ahadiff/concepts/schemas.py`):
```python
class ConceptNode(BaseModel):
    term_key: str           # compute_term_key() 的输出，主键
    canonical_term: str     # 英文规范术语 (e.g. "dependency_injection")
    display_name: str       # 本地化显示名 (e.g. "依赖注入")
    aliases: list[str] = [] # 等价形式 (e.g. ["DI", "IoC", "控制反转"])
    lang: str               # display_name 的语言
```

**合并策略**: 新概念提取时，先 `compute_term_key(new_term)`，查找 `concepts.jsonl` 是否已有相同 `term_key`：
- 匹配 → 将 `new_term` 加入 `aliases[]`（去重）
- 不匹配 → 检查 `aliases[]` 是否包含 `new_term`（模糊匹配用 `compute_term_key` 归一化后比较）
- 均不匹配 → 新建节点

**测试用例** (`tests/unit/test_concept_identity.py`):
```python
@pytest.mark.parametrize("term,expected_key", [
    ("Dependency Injection", "dependency_injection"),
    ("dependency-injection", "dependency_injection"),
    ("DEPENDENCY_INJECTION", "dependency_injection"),
    ("DI (Dependency Injection)", "di_dependency_injection"),
    ("依赖注入", "依赖注入"),
    ("café", "cafe"),
])
def test_compute_term_key(term, expected_key):
    assert compute_term_key(term) == expected_key

def test_alias_dedup():
    node = ConceptNode(term_key="di", canonical_term="dependency_injection",
                       display_name="依赖注入", aliases=["DI"], lang="zh-CN")
    # 添加已存在 alias 不应重复
    new_aliases = list(set(node.aliases + ["DI", "IoC"]))
    assert new_aliases == ["DI", "IoC"]
```

---

## CC-NEW-6: Archive Bomb 让 Secret Scan DoS

**文件**: `src/ahadiff/safety/archive_walker.py`

**函数**: `safe_extract(archive_path: str, config: ArchivePolicy) -> list[ExtractedFile]`

**具体阈值** (可配置，默认值):
```python
# src/ahadiff/safety/archive_walker.py
from dataclasses import dataclass

@dataclass
class ArchivePolicy:
    max_depth: int = 3              # 最大嵌套层级
    max_total_size_mb: float = 50   # 解压后总大小上限 (MB)
    max_file_count: int = 500       # 最大文件数
    max_single_file_mb: float = 10  # 单文件解压大小上限
    timeout_seconds: float = 30     # 总耗时上限
    allowed_extensions: set[str] = None  # None = 全部允许
```

**超限行为**:
```python
class ArchiveLimitExceeded(Exception):
    def __init__(self, reason: str, partial_results: list):
        self.reason = reason  # "depth_exceeded" | "size_exceeded" | "count_exceeded" | "timeout"
        self.partial_results = partial_results

def safe_extract(archive_path: str, policy: ArchivePolicy | None = None) -> list:
    """
    安全解压。超限时:
    1. 立即停止解压
    2. 返回已扫描的部分结果
    3. 在 redaction_report 中记录 archive_scan_partial=true + reason
    4. 不阻塞主流程，但对未扫描部分标记 scan_coverage="partial"
    """
    policy = policy or ArchivePolicy()
    # ... 实现略
```

**Config 可配置性** (`config.toml`):
```toml
[security.archive]
max_depth = 3
max_total_size_mb = 50
max_file_count = 500
timeout_seconds = 30
```

**测试用例** (`tests/unit/test_archive_walker.py`):
```python
def test_depth_limit(tmp_path):
    # 创建 4 层嵌套 zip
    nested = create_nested_zip(tmp_path, depth=4)
    with pytest.raises(ArchiveLimitExceeded) as exc:
        safe_extract(str(nested), ArchivePolicy(max_depth=3))
    assert exc.value.reason == "depth_exceeded"

def test_size_limit(tmp_path):
    big_zip = create_zip_with_size(tmp_path, size_mb=60)
    with pytest.raises(ArchiveLimitExceeded) as exc:
        safe_extract(str(big_zip), ArchivePolicy(max_total_size_mb=50))
    assert exc.value.reason == "size_exceeded"

def test_timeout(tmp_path, mocker):
    mocker.patch("time.time", side_effect=incremental_time(step=35))
    with pytest.raises(ArchiveLimitExceeded) as exc:
        safe_extract(str(some_zip), ArchivePolicy(timeout_seconds=30))
    assert exc.value.reason == "timeout"
```

---

## CC-NEW-7: SSR 页面和 API 语言不一致

**文件**: `src/ahadiff/serve/middleware.py`

**Cookie 名**: `ahadiff_lang`

**过期策略**: `Max-Age=31536000`（1 年），`SameSite=Lax`，`Path=/`。

**Serve Middleware 实现**:
```python
# src/ahadiff/serve/middleware.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

COOKIE_NAME = "ahadiff_lang"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year

class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        locale = self._resolve_locale(request)
        request.state.locale = locale
        response: Response = await call_next(request)
        # 确保 cookie 与解析结果一致（自动修复缺失 cookie）
        if request.cookies.get(COOKIE_NAME) != locale:
            response.set_cookie(
                COOKIE_NAME, locale,
                max_age=COOKIE_MAX_AGE, samesite="lax", path="/",
            )
        return response

    def _resolve_locale(self, request: Request) -> str:
        """优先级: cookie > Accept-Language > config > 'en'"""
        from ahadiff.i18n.resolver import normalize_locale
        # 1. Cookie
        cookie_val = request.cookies.get(COOKIE_NAME)
        if cookie_val:
            return normalize_locale(cookie_val)
        # 2. Accept-Language header
        accept = request.headers.get("accept-language", "")
        if accept:
            primary = accept.split(",")[0].split(";")[0].strip()
            return normalize_locale(primary)
        # 3. Config fallback
        return "en"
```

**API 端点** (`PUT /api/locale`):
```python
@router.put("/api/locale")
async def set_locale(request: Request):
    body = await request.json()
    new_locale = normalize_locale(body.get("lang", "en"))
    response = JSONResponse({"locale": new_locale})
    response.set_cookie(COOKIE_NAME, new_locale, max_age=COOKIE_MAX_AGE, samesite="lax", path="/")
    return response
```

**一致性保证**: SSR 模板渲染和 API JSON 响应都从 `request.state.locale` 读取，由同一 middleware 设置，不可能不一致。

**测试用例** (`tests/unit/test_locale_middleware.py`):
```python
@pytest.mark.anyio
async def test_cookie_takes_priority(client):
    resp = await client.get("/", cookies={"ahadiff_lang": "zh-CN"})
    assert "lang=\"zh-CN\"" in resp.text

@pytest.mark.anyio
async def test_accept_language_fallback(client):
    resp = await client.get("/", headers={"Accept-Language": "zh-Hans-CN,zh;q=0.9"})
    assert "lang=\"zh-CN\"" in resp.text

@pytest.mark.anyio
async def test_api_and_page_consistent(client):
    await client.put("/api/locale", json={"lang": "zh-CN"})
    page_resp = await client.get("/")
    api_resp = await client.get("/api/locale")
    assert api_resp.json()["locale"] == "zh-CN"
    assert "lang=\"zh-CN\"" in page_resp.text
```

---

## CC-NEW-8: ~~Static 按钮可点击但无法提交~~ — **N/A（已取消 static 模式）**

> 第五轮审查决策：前端直接用 React SPA，取消 file:// 静态模式。此 CC 不再适用。

**原文件**: `viewer/templates/components/_action_button.html` + `viewer/static/app.js`

**HTML 属性规范**:
```html
<!-- 每个交互按钮必须声明 -->
<button
  class="aha-action"
  data-mode="serve"
  data-requires-js="true"
  data-cli-fallback="ahadiff mark wrong c020"
  data-action="/api/signals/mark-wrong"
  data-payload='{"claim_id":"c020"}'
>
  Mark Wrong
</button>
```

| 属性 | 用途 |
|------|------|
| `data-mode` | `"serve"` = 仅 serve 模式可用；`"static"` = file:// 也可用 |
| `data-requires-js` | `"true"` = 需要 JS 运行时 |
| `data-cli-fallback` | 可复制的 CLI 等效命令 |
| `data-action` | Serve 模式下的 API endpoint |
| `data-payload` | JSON payload 模板 |

**JS 检测逻辑** (`viewer/static/app.js`):
```javascript
// app.js — Progressive Enhancement 入口
(function() {
    const isServe = document.documentElement.dataset.mode === "serve";
    // 检测方法: serve 模式下 data_bundle 中注入 { "mode": "serve" }

    document.querySelectorAll(".aha-action[data-requires-js]").forEach(btn => {
        if (isServe) {
            // Serve 模式: 正常绑定 click handler
            btn.addEventListener("click", handleAction);
            btn.removeAttribute("disabled");
        } else {
            // Static 模式: 替换为降级 UI
            btn.disabled = true;
            btn.classList.add("aha-action--static");
            btn.setAttribute("title", btn.dataset.cliFallback);

            // 注入 tooltip 提示
            const hint = document.createElement("span");
            hint.className = "aha-cli-hint";
            hint.textContent = btn.dataset.cliFallback;
            btn.parentNode.insertBefore(hint, btn.nextSibling);
        }
    });
})();
```

**降级 UI 文案** (通过 i18n catalog):
```json
{
  "Static": {
    "actionDisabled": "This action requires `ahadiff serve` / 此操作需要启动 `ahadiff serve`",
    "copyCommand": "Copy CLI command / 复制 CLI 命令",
    "clickToCopy": "Click to copy: {command} / 点击复制: {command}"
  }
}
```

**CSS 降级样式**:
```css
.aha-action--static {
    opacity: 0.5;
    cursor: not-allowed;
    position: relative;
}
.aha-action--static::after {
    content: "CLI ↗";
    font-size: 0.7em;
    position: absolute;
    top: -4px;
    right: -4px;
}
.aha-cli-hint {
    display: block;
    font-family: monospace;
    font-size: 0.8em;
    color: var(--color-muted);
    margin-top: 4px;
    cursor: pointer;  /* 点击复制 */
}
```

**测试用例** (`tests/e2e/test_static_fallback.py` — Playwright):
```python
def test_static_buttons_disabled(page):
    page.goto("file:///path/to/output/index.html")
    btn = page.locator(".aha-action[data-mode='serve']")
    assert btn.is_disabled()
    assert btn.get_attribute("title") == "ahadiff mark wrong c020"

def test_serve_buttons_enabled(serve_page):
    btn = serve_page.locator(".aha-action[data-mode='serve']")
    assert not btn.is_disabled()

def test_cli_hint_visible_in_static(page):
    page.goto("file:///path/to/output/index.html")
    hint = page.locator(".aha-cli-hint")
    assert hint.is_visible()
    assert "ahadiff" in hint.text_content()
```

---

## 总结矩阵

| CC | 核心文件 | Schema 变更 | 测试数 |
|----|---------|------------|--------|
| CC-NEW-1 | `i18n/resolver.py` | 无 | 8 parametrize |
| CC-NEW-2 | `llm/language_guard.py` | `RunRecord.mixed_language_output: bool` | 4 |
| CC-NEW-3 | `safety/redaction.py` + `claims/schemas.py` | `EvidenceAnchor` 改为 `file_id`+`display_path` | 4 |
| CC-NEW-4 | `serve/middleware.py` + `review/database.py` | `learning_signals.idempotency_key UNIQUE` | 2 |
| CC-NEW-5 | `concepts/identity.py` | `ConceptNode.term_key` + `aliases[]` | 7 parametrize |
| CC-NEW-6 | `safety/archive_walker.py` | 无（config 新增 `[security.archive]`） | 3 |
| CC-NEW-7 | `serve/middleware.py` | 无 | 3 |
| CC-NEW-8 | ~~N/A — 已取消 static 模式~~ | — | — |
