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
diff --git a/src/cart.py b/src/cart.py
@@ -12,7 +12,10 @@ def apply_discount(total, code):
-    if code == "WELCOME10":
-        return total * 0.9
+    if code == "WELCOME10" and total >= 5000:
+        return round(total * 0.9, 2)
+    if code == "WELCOME10":
+        return total
     return total
""".strip()


def _demo_preview(locale: Literal["en", "zh-CN"]) -> DemoLearnPreviewResponse:
    if locale == "zh-CN":
        return DemoLearnPreviewResponse(
            locale="zh-CN",
            sample_diff=_SAMPLE_DIFF,
            claims=[
                DemoClaimPreview(
                    text="WELCOME10 现在只会给金额至少 5000 的订单打折。",
                    status="verified",
                    evidence="src/cart.py:12-13",
                ),
                DemoClaimPreview(
                    text="未达到门槛的 WELCOME10 订单会返回原价。",
                    status="verified",
                    evidence="src/cart.py:14-15",
                ),
            ],
            lesson_snippet=(
                "这次 diff 把折扣资格从“只要有优惠码”收紧为"
                "“优惠码加金额门槛”。AhaDiff 会把行为变化绑定到具体行号，"
                "并生成可以主动回忆的测验。"
            ),
            quiz=DemoQuizPreview(
                question="WELCOME10 在什么情况下会应用 10% 折扣？",
                choices=[
                    "任意订单都可以",
                    "订单金额至少 5000 时",
                    "只有没有优惠码时",
                    "只在返回 total 之前",
                ],
                answer_index=1,
            ),
        )
    return DemoLearnPreviewResponse(
        locale="en",
        sample_diff=_SAMPLE_DIFF,
        claims=[
            DemoClaimPreview(
                text="WELCOME10 now discounts only orders of at least 5000.",
                status="verified",
                evidence="src/cart.py:12-13",
            ),
            DemoClaimPreview(
                text="WELCOME10 orders below the threshold now return the original total.",
                status="verified",
                evidence="src/cart.py:14-15",
            ),
        ],
        lesson_snippet=(
            "This diff tightens discount eligibility from any matching code to matching "
            "code plus a minimum order total. AhaDiff ties that behavior change to exact "
            "evidence and turns it into recall practice."
        ),
        quiz=DemoQuizPreview(
            question="When does WELCOME10 apply a 10% discount?",
            choices=[
                "For every order",
                "When the order total is at least 5000",
                "Only when no code is present",
                "Only after returning total",
            ],
            answer_index=1,
        ),
    )


async def get_demo_learn_preview(request: Request) -> JSONResponse:
    payload = _demo_preview(request_locale(request)).model_dump(mode="json")
    return JSONResponse(payload)


__all__ = ["get_demo_learn_preview"]
