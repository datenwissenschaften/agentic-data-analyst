"""Internal capability objects produced only after semantic validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from agentic_data_analyst.models import AnalysisIR, LimitStep


@dataclass(frozen=True, slots=True)
class AuthorizedDataset:
    """Canonical catalog path and columns authorized for one input alias."""

    dataset: str
    alias: str
    path: Path
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidatedAnalysis:
    """Capability passed to the compiler after catalog and lineage checks."""

    ir: AnalysisIR
    datasets: tuple[AuthorizedDataset, ...]
    output_columns: tuple[str, ...]

    def dataset_for_alias(self, alias: str) -> AuthorizedDataset:
        for dataset in self.datasets:
            if dataset.alias == alias:
                return dataset
        raise ValueError(f"No authorized dataset for alias: {alias}")

    def before_final_limit(self) -> ValidatedAnalysis:
        final_step = self.ir.steps[-1]
        if not isinstance(final_step, LimitStep):
            raise ValueError("Validated analysis does not end with a limit")
        pre_limit_ir = self.ir.model_copy(update={"steps": self.ir.steps[:-1], "output": final_step.input})
        return replace(self, ir=pre_limit_ir)
