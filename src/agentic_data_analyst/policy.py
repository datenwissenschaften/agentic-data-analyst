"""Central safety and resource limits for model-produced analyses."""

from __future__ import annotations

from dataclasses import dataclass, fields

MAX_QUESTION_CHARS = 2_000
MAX_IR_INPUTS = 8
MAX_IR_STEPS = 30
MAX_SELECTED_COLUMNS_PER_INPUT = 128
MAX_PLAN_STEPS = 20
MAX_EXPRESSION_ARGUMENTS = 20
MAX_LITERAL_CHARS = 4_000
MAX_PROJECT_COLUMNS = 128
MAX_GROUP_KEYS = 32
MAX_AGGREGATIONS = 64
MAX_SORT_KEYS = 16
MAX_RESULT_ROWS_HARD = 10_000


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    """Operational limits applied by semantic validation."""

    max_catalog_candidates: int = 8
    max_inputs: int = 8
    max_selected_columns_per_input: int = 64
    max_total_selected_columns: int = 128
    max_steps: int = 30
    max_joins: int = 6
    max_project_columns: int = 64
    max_group_keys: int = 16
    max_aggregations_per_step: int = 32
    max_total_aggregations: int = 64
    max_sort_keys: int = 8
    max_expression_depth: int = 12
    max_expression_nodes: int = 100
    max_total_expression_nodes: int = 500
    max_result_rows: int = 100

    def __post_init__(self) -> None:
        for item in fields(self):
            if getattr(self, item.name) <= 0:
                raise ValueError(f"{item.name} must be greater than zero")
        hard_limits = {
            "max_inputs": MAX_IR_INPUTS,
            "max_selected_columns_per_input": MAX_SELECTED_COLUMNS_PER_INPUT,
            "max_steps": MAX_IR_STEPS,
            "max_project_columns": MAX_PROJECT_COLUMNS,
            "max_group_keys": MAX_GROUP_KEYS,
            "max_aggregations_per_step": MAX_AGGREGATIONS,
            "max_sort_keys": MAX_SORT_KEYS,
            "max_result_rows": MAX_RESULT_ROWS_HARD,
        }
        for name, maximum in hard_limits.items():
            if getattr(self, name) > maximum:
                raise ValueError(f"{name} cannot exceed structural limit {maximum}")
