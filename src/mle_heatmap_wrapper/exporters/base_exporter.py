from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from ..core.config import config
from ..core.logger import get_logger
from ..models.data_models import ProcessingResult

class BaseExporter(ABC):
    """Abstract exporter class."""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or config.paths.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def export(self, result: ProcessingResult) -> Path:
        """Export one result."""

    def export_batch(self, results: List[ProcessingResult]) -> List[Path]:
        exported = []
        for result in results:
            if not result.success:
                continue
            try:
                exported.append(self.export(result))
            except Exception as exc:
                self.logger.error("Failed to export %s: %s", result.metric_type, exc)
        return exported