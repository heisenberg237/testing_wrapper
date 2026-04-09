"""Digital health metrics collection for wrapper executions."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from .logger import get_logger

logger = get_logger(__name__)


class ExecutionStatus(Enum):
    """Execution status values."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    IN_PROGRESS = "in_progress"


@dataclass
class ExecutionMetrics:
    """Runtime counters and KPIs for one execution."""

    execution_id: str
    part_number: str
    supplier: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: ExecutionStatus = ExecutionStatus.IN_PROGRESS

    sections_processed: int = 0
    sections_expected: int = 0
    sections_failed: int = 0

    metrics_generated: List[str] = field(default_factory=list)
    processing_duration_seconds: float = 0.0
    input_points_count: int = 0
    output_rows_count: int = 0

    warnings_count: int = 0
    errors_count: int = 0
    error_messages: List[str] = field(default_factory=list)
    custom_metrics: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.execution_id:
            self.execution_id = (
                f"{self.part_number}_{self.supplier}_{self.start_time:%Y%m%d_%H%M%S}"
            )

    def mark_complete(self) -> None:
        self.end_time = datetime.now()
        self.processing_duration_seconds = (
            self.end_time - self.start_time
        ).total_seconds()
        if self.errors_count > 0:
            self.status = ExecutionStatus.FAILURE
        elif self.warnings_count > 0 or self.sections_failed > 0:
            self.status = ExecutionStatus.PARTIAL_SUCCESS
        else:
            self.status = ExecutionStatus.SUCCESS

    def add_error(self, message: str) -> None:
        self.errors_count += 1
        self.error_messages.append(message)
        logger.error("Error recorded: %s", message)

    def add_warning(self) -> None:
        self.warnings_count += 1

    def add_custom_metric(self, name: str, value: float) -> None:
        self.custom_metrics[name] = value

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat()
        data["end_time"] = self.end_time.isoformat() if self.end_time else None
        data["status"] = self.status.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def get_summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            f"Execution Summary - {self.execution_id}",
            "=" * 60,
            f"Part Number: {self.part_number}",
            f"Supplier: {self.supplier}",
            f"Status: {self.status.value.upper()}",
            f"Duration: {self.processing_duration_seconds:.2f}s",
            "",
            "Sections:",
            f"  - Expected: {self.sections_expected}",
            f"  - Processed: {self.sections_processed}",
            f"  - Failed: {self.sections_failed}",
            "",
            "Data:",
            f"  - Input points: {self.input_points_count:,}",
            f"  - Output rows: {self.output_rows_count:,}",
            "",
            f"Metrics Generated: {', '.join(self.metrics_generated) if self.metrics_generated else 'None'}",
            "",
            "Quality:",
            f"  - Warnings: {self.warnings_count}",
            f"  - Errors: {self.errors_count}",
        ]
        if self.error_messages:
            lines.append("")
            lines.append("Errors:")
            for message in self.error_messages[:5]:
                lines.append(f"  - {message}")
            if len(self.error_messages) > 5:
                lines.append(f"  ... and {len(self.error_messages) - 5} more")
        if self.custom_metrics:
            lines.append("")
            lines.append("Custom Metrics:")
            for name, value in self.custom_metrics.items():
                lines.append(f"  - {name}: {value}")
        lines.append("=" * 60)
        lines.append("")
        return "\n".join(lines)


class MetricsCollector:
    """Stateful execution metrics manager."""

    def __init__(self):
        self._current_metrics: Optional[ExecutionMetrics] = None
        self._history: List[ExecutionMetrics] = []

    def start_execution(
        self,
        part_number: str,
        supplier: str,
        sections_expected: int,
        execution_id: Optional[str] = None,
    ) -> ExecutionMetrics:
        self._current_metrics = ExecutionMetrics(
            execution_id=execution_id or "",
            part_number=part_number,
            supplier=supplier,
            sections_expected=sections_expected,
        )
        logger.info("Started execution: %s", self._current_metrics.execution_id)
        return self._current_metrics

    def get_current_metrics(self) -> Optional[ExecutionMetrics]:
        return self._current_metrics

    def finalize_execution(self) -> ExecutionMetrics:
        if not self._current_metrics:
            raise RuntimeError("No execution in progress")
        self._current_metrics.mark_complete()
        self._history.append(self._current_metrics)
        finalized = self._current_metrics
        self._current_metrics = None
        logger.info(finalized.get_summary())
        return finalized

    def get_history(self) -> List[ExecutionMetrics]:
        return self._history.copy()


metrics_collector = MetricsCollector()
