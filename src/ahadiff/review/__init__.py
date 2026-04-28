from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import (
        CURRENT_SCHEMA_VERSION,
        LossyImportOutcome,
        UpgradeOutcome,
        backup_review_db,
        check_review_db,
        connect_review_db,
        count_concepts,
        delete_result_event,
        finalize_targeted_verify_event,
        import_cards_from_jsonl,
        import_cards_from_runs,
        import_concepts_from_jsonl,
        import_results_tsv_lossy,
        initialize_review_db,
        insert_learning_signal,
        list_due_cards,
        load_concepts_from_db,
        load_result_event_by_run_and_id,
        load_result_events_from_db,
        record_card_review,
        restore_review_db,
        select_result_tsv_rows,
        set_card_queue_state,
        sync_result_event,
        upgrade_review_db,
        upsert_concept,
        upsert_concepts_batch,
    )
    from .optimizer import OptimizeResult, optimize_weights
    from .scheduler import (
        DEFAULT_DESIRED_RETENTION,
        DEFAULT_MAXIMUM_INTERVAL,
        ScheduledReview,
        default_scheduler_parameters,
        default_weights_json,
        normalize_fsrs_state,
        rating_for_answer,
        review_fsrs_card,
        scheduler_version,
        snapshot_card_state,
    )
    from .schemas import CardQueueAction, DueReviewCard, ReviewAnswer, ReviewDbCheck, ReviewUpdate

_DATABASE_EXPORTS = {
    "CURRENT_SCHEMA_VERSION",
    "LossyImportOutcome",
    "UpgradeOutcome",
    "backup_review_db",
    "check_review_db",
    "connect_review_db",
    "count_concepts",
    "delete_result_event",
    "finalize_targeted_verify_event",
    "import_cards_from_jsonl",
    "import_cards_from_runs",
    "import_concepts_from_jsonl",
    "import_results_tsv_lossy",
    "initialize_review_db",
    "insert_learning_signal",
    "list_due_cards",
    "load_concepts_from_db",
    "load_result_event_by_run_and_id",
    "load_result_events_from_db",
    "record_card_review",
    "restore_review_db",
    "select_result_tsv_rows",
    "set_card_queue_state",
    "sync_result_event",
    "upgrade_review_db",
    "upsert_concept",
    "upsert_concepts_batch",
}
_SCHEDULER_EXPORTS = {
    "DEFAULT_DESIRED_RETENTION",
    "DEFAULT_MAXIMUM_INTERVAL",
    "ScheduledReview",
    "default_scheduler_parameters",
    "default_weights_json",
    "normalize_fsrs_state",
    "rating_for_answer",
    "review_fsrs_card",
    "scheduler_version",
    "snapshot_card_state",
}
_SCHEMA_EXPORTS = {
    "CardQueueAction",
    "DueReviewCard",
    "ReviewAnswer",
    "ReviewDbCheck",
    "ReviewUpdate",
}
_OPTIMIZER_EXPORTS = {"OptimizeResult", "optimize_weights"}

_EXPORT_MODULES = {
    **dict.fromkeys(_DATABASE_EXPORTS, "database"),
    **dict.fromkeys(_SCHEDULER_EXPORTS, "scheduler"),
    **dict.fromkeys(_SCHEMA_EXPORTS, "schemas"),
    **dict.fromkeys(_OPTIMIZER_EXPORTS, "optimizer"),
}

__all__ = [
    "backup_review_db",
    "CardQueueAction",
    "check_review_db",
    "connect_review_db",
    "count_concepts",
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_DESIRED_RETENTION",
    "DEFAULT_MAXIMUM_INTERVAL",
    "default_scheduler_parameters",
    "default_weights_json",
    "delete_result_event",
    "DueReviewCard",
    "finalize_targeted_verify_event",
    "import_cards_from_jsonl",
    "import_cards_from_runs",
    "import_concepts_from_jsonl",
    "import_results_tsv_lossy",
    "initialize_review_db",
    "insert_learning_signal",
    "list_due_cards",
    "load_concepts_from_db",
    "load_result_event_by_run_and_id",
    "load_result_events_from_db",
    "LossyImportOutcome",
    "normalize_fsrs_state",
    "OptimizeResult",
    "optimize_weights",
    "rating_for_answer",
    "record_card_review",
    "restore_review_db",
    "ReviewAnswer",
    "ReviewDbCheck",
    "review_fsrs_card",
    "ReviewUpdate",
    "ScheduledReview",
    "scheduler_version",
    "select_result_tsv_rows",
    "set_card_queue_state",
    "snapshot_card_state",
    "sync_result_event",
    "UpgradeOutcome",
    "upgrade_review_db",
    "upsert_concept",
    "upsert_concepts_batch",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
