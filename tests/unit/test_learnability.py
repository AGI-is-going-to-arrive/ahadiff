from __future__ import annotations

from ahadiff.lesson.learnability import assess_learnability, compute_learnability_score


def _source_line_edit_patch(index: int) -> str:
    return (
        f"diff --git a/src/file_{index}.py b/src/file_{index}.py\n"
        f"--- a/src/file_{index}.py\n"
        f"+++ b/src/file_{index}.py\n"
        "@@ -1 +1 @@\n"
        f"-value_{index} = 1\n"
        f"+value_{index} = 2\n"
    )


def _source_structural_churn_patch(index: int) -> str:
    old_lines = "".join(f"-    value_{line} = {line}\n" for line in range(12))
    new_lines = "".join(f"+    value_{line} = {line} + 1\n" for line in range(12))
    return f"""\
diff --git a/src/churn_{index}.py b/src/churn_{index}.py
--- a/src/churn_{index}.py
+++ b/src/churn_{index}.py
@@ -1,13 +1,13 @@ def calculate_{index}():
 def calculate_{index}():
{old_lines}{new_lines}"""


def test_learnability_scores_logic_change_above_threshold() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,6 @@
-def retry_once():
-    return 1
+def retry_once():
+    for attempt in range(3):
+        try:
+            return attempt
+        except Exception:
+            continue
"""

    assessment = assess_learnability(patch)

    assert compute_learnability_score(patch) == assessment.score
    assert assessment.score >= assessment.threshold
    assert assessment.skip_lesson_quiz is False
    assert "logic_structure_detected" in assessment.reasons


def test_learnability_skips_lockfile_churn() -> None:
    patch = """\
diff --git a/package-lock.json b/package-lock.json
--- a/package-lock.json
+++ b/package-lock.json
@@ -10,3 +10,3 @@
-      "version": "1.0.0",
-      "resolved": "https://registry.npmjs.org/demo/-/demo-1.0.0.tgz",
-      "integrity": "sha512-old"
+      "version": "1.0.1",
+      "resolved": "https://registry.npmjs.org/demo/-/demo-1.0.1.tgz",
+      "integrity": "sha512-new"
"""

    assessment = assess_learnability(patch)

    assert assessment.score < assessment.threshold
    assert assessment.skip_lesson_quiz is True
    assert "low_signal_file_types" in assessment.reasons


def test_learnability_skips_tiny_non_structural_source_edit() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-message = "helo"
+message = "hello"
"""

    assessment = assess_learnability(patch)

    assert assessment.score < assessment.threshold
    assert assessment.skip_lesson_quiz is True
    assert "small_non_structural_change" in assessment.reasons


def test_learnability_force_learn_overrides_skip() -> None:
    patch = """\
diff --git a/package-lock.json b/package-lock.json
--- a/package-lock.json
+++ b/package-lock.json
@@ -1 +1 @@
-  "version": "1.0.0"
+  "version": "1.0.1"
"""

    assessment = assess_learnability(patch, force_learn=True)

    assert assessment.score < assessment.threshold
    assert assessment.forced is True
    assert assessment.skip_lesson_quiz is False


def test_learnability_skips_empty_diff() -> None:
    assessment = assess_learnability("")

    assert compute_learnability_score("") == assessment.score
    assert assessment.score == 0.0
    assert assessment.skip_lesson_quiz is True
    assert assessment.factors.as_dict() == {
        "complexity": 0.0,
        "novelty": 0.0,
        "pattern": 0.0,
    }
    assert assessment.reasons == ("empty_diff",)


def test_learnability_skips_binary_diff() -> None:
    patch = """\
diff --git a/assets/logo.png b/assets/logo.png
index 1111111..2222222 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""

    assessment = assess_learnability(patch)

    assert 0.0 <= assessment.score < assessment.threshold
    assert assessment.skip_lesson_quiz is True
    assert assessment.factors.pattern == 0.0
    assert "small_non_structural_change" in assessment.reasons


def test_learnability_skips_all_context_diff_without_changed_lines() -> None:
    patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 unchanged = True
 still_unchanged = True
"""

    assessment = assess_learnability(patch)

    assert assessment.score < assessment.threshold
    assert assessment.skip_lesson_quiz is True
    assert assessment.factors.pattern == 0.0
    assert assessment.reasons == ("small_non_structural_change",)


def test_learnability_handles_many_changed_files() -> None:
    patch = "".join(_source_line_edit_patch(index) for index in range(50))

    assessment = assess_learnability(patch)

    assert 0.0 <= assessment.score <= 1.0
    assert assessment.score >= assessment.threshold
    assert assessment.skip_lesson_quiz is False
    assert assessment.reasons == ("mixed_change_pattern",)


def test_learnability_skips_rename_only_without_hunks() -> None:
    patch = """\
diff --git a/src/old_name.py b/src/new_name.py
similarity index 100%
rename from src/old_name.py
rename to src/new_name.py
"""

    assessment = assess_learnability(patch)

    assert assessment.score < assessment.threshold
    assert assessment.skip_lesson_quiz is True
    assert assessment.reasons == ("small_non_structural_change",)


def test_learnability_keeps_structural_delete_above_threshold() -> None:
    patch = """\
diff --git a/src/legacy.py b/src/legacy.py
deleted file mode 100644
--- a/src/legacy.py
+++ /dev/null
@@ -1,5 +0,0 @@
-def legacy_retry():
-    for attempt in range(3):
-        if attempt:
-            return attempt
-    return 0
"""

    assessment = assess_learnability(patch)

    assert assessment.score >= assessment.threshold
    assert assessment.skip_lesson_quiz is False
    assert "logic_structure_detected" in assessment.reasons


def test_learnability_large_high_signal_source_churn_saturates_safely() -> None:
    patch = "".join(_source_structural_churn_patch(index) for index in range(8))

    assessment = assess_learnability(patch)

    assert 0.8 <= assessment.score <= 1.0
    assert assessment.skip_lesson_quiz is False
    assert "logic_structure_detected" in assessment.reasons
