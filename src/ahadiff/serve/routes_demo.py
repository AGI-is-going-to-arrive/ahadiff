"""Deterministic demo endpoints for first-run guidance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from starlette.responses import JSONResponse

from ahadiff.contracts.serve_demo import (
    DemoClaimPreview,
    DemoLearnPreviewResponse,
    DemoQuizPreview,
)

from .locale import request_locale

if TYPE_CHECKING:
    from starlette.requests import Request


_SAMPLE_DIFF = """
diff --git a/app/main.py b/app/main.py
@@ -8,6 +8,12 @@ app = FastAPI()
+@app.middleware("http")
+async def no_store_api_responses(request: Request, call_next):
+    response = await call_next(request)
+    if request.url.path.startswith("/api/"):
+        response.headers["cache-control"] = "no-store"
+    return response
 @app.get("/health")
""".strip()


def _demo_preview(locale: Literal["en", "zh-CN"]) -> DemoLearnPreviewResponse:
    if locale == "zh-CN":
        return DemoLearnPreviewResponse(
            locale="zh-CN",
            sample_diff=_SAMPLE_DIFF,
            claims=[
                DemoClaimPreview(
                    text=(
                        '新增函数通过 @app.middleware("http") 注册为 HTTP 中间件，'
                        "而不是普通路由处理器。"
                    ),
                    status="verified",
                    evidence="app/main.py:8-9",
                ),
                DemoClaimPreview(
                    text="中间件会先 await call_next(request)，让正常路由先生成响应。",
                    status="verified",
                    evidence="app/main.py:10",
                ),
                DemoClaimPreview(
                    text="只有路径以 /api/ 开头的请求，响应才会被加上 cache-control: no-store。",
                    status="verified",
                    evidence="app/main.py:11-12",
                ),
            ],
            lesson_snippet=(
                "vibe coding 后，这类几行 FastAPI 中间件最容易被直接合并但没真正理解。"
                "AhaDiff 会把 AI 写出的 diff 拆成带行号证据的 claims：它是中间件，"
                "call_next 保留正常路由响应，只有 /api/ 响应会被加上 no-store。"
                "AI 写完，Diff 教回。"
            ),
            quiz=DemoQuizPreview(
                question="这个中间件在什么情况下会给响应加上 cache-control: no-store？",
                choices=[
                    "请求路径以 /api/ 开头时",
                    "每一个静态资源响应",
                    "只有 /health 路由",
                    "永远不会，因为 call_next 返回 None",
                ],
                answer_index=0,
            ),
        )
    return DemoLearnPreviewResponse(
        locale="en",
        sample_diff=_SAMPLE_DIFF,
        claims=[
            DemoClaimPreview(
                text=(
                    "The added function is registered as an HTTP middleware, "
                    "not as a route handler."
                ),
                status="verified",
                evidence="app/main.py:8-9",
            ),
            DemoClaimPreview(
                text=(
                    "The middleware lets the normal route handler build the response "
                    "by awaiting call_next(request)."
                ),
                status="verified",
                evidence="app/main.py:10",
            ),
            DemoClaimPreview(
                text=(
                    "Only requests whose path starts with /api/ receive cache-control: "
                    "no-store on the response."
                ),
                status="verified",
                evidence="app/main.py:11-12",
            ),
        ],
        lesson_snippet=(
            "Vibe coding often leaves you with a tiny middleware that changes more than it "
            "looks like. AhaDiff teaches the diff back as verified claims: this is "
            "middleware, call_next preserves the normal route response, and only /api/ "
            "responses get no-store. AI writes; the diff teaches back."
        ),
        quiz=DemoQuizPreview(
            question="When does this middleware add cache-control: no-store?",
            choices=[
                "Only when the request path starts with /api/",
                "For every static asset response",
                "Only for the /health route",
                "Never, because call_next returns None",
            ],
            answer_index=0,
        ),
    )


async def get_demo_learn_preview(request: Request) -> JSONResponse:
    payload = _demo_preview(request_locale(request)).model_dump(mode="json")
    return JSONResponse(payload)


__all__ = ["get_demo_learn_preview"]
