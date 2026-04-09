"""CSV and metrics exporters."""

from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from ..core.config import config
from ..core.logger import get_logger
from ..models.data_models import PieceMetadata, ProcessingResult
from ..exporters.base_exporter import BaseExporter


class CSVExporter(BaseExporter):
    """CSV exporter for metric data."""

    def __init__(self, output_dir: Path = None, include_timestamp: bool = False):
        super().__init__(output_dir)
        self.include_timestamp = include_timestamp

    def export(self, result: ProcessingResult) -> Path:
        filename = result.part_config.get_output_filename(result.metric_type, result.piece_metadata.serial_number)
        if self.include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem, ext = filename.rsplit(".", 1)
            filename = f"{stem}_{timestamp}.{ext}"
        output_path = self.output_dir / filename

        df = result.data.copy()
        df = df.pivot(
            index="radius",
            columns="section",
            values="value",
        )

        df.index = "R" + df.index.astype(str)

        df.to_csv(
            output_path, encoding="utf-8", float_format="%.6f"
        )

        return output_path

    def export_piece_results(
        self, results: List[ProcessingResult], piece_metadata: PieceMetadata
    ) -> Path:
        successful = [res for res in results if res.success and not res.data.empty]
        if not successful:
            raise ValueError("No successful metric results to export")

        output_paths = []
        for result in successful:
            frame = result.data.copy()
            
            frame = frame.pivot(
                index="radius",
                columns="section",
                values="value",
            )

            frame.index = "R" + frame.index.astype(str)

            filename = result.part_config.get_output_filename(result.metric_type, result.piece_metadata.serial_number)
            output_path = self.output_dir / filename
            frame.to_csv(output_path, index=False, encoding="utf-8", float_format="%.6f")

            output_paths.append(output_path)
        return output_path

    def _build_piece_filename(self, piece_metadata: PieceMetadata) -> str:
        serial = self._sanitize(piece_metadata.serial_number)
        supplier = self._sanitize(piece_metadata.normalized_supplier)
        part_number = self._sanitize(piece_metadata.part_number)
        date = self._sanitize(piece_metadata.measurement_date)
        operation = self._sanitize(self.part_config.operation)
        if self.include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{serial}_{supplier}_{part_number}_{date}_{timestamp}.csv"
        return f"{serial}_{supplier}_{part_number}_{date}.csv"

    def _sanitize(self, value: str) -> str:
        clean = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value)
        )
        return clean or "UNKNOWN"


class MetricsExporter:
    """Exports execution metrics and human-readable summaries."""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or config.paths.output_dir / "metrics"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(self.__class__.__name__)

    def export_metrics(self, metrics, filename: str = None) -> Path:
        if filename is None:
            filename = f"metrics_{metrics.execution_id}.json"
        output_path = self.output_dir / filename
        output_path.write_text(metrics.to_json(), encoding="utf-8")
        return output_path

    def export_summary(self, metrics, filename: str = None) -> Path:
        if filename is None:
            filename = f"summary_{metrics.execution_id}.txt"
        output_path = self.output_dir / filename
        output_path.write_text(metrics.get_summary(), encoding="utf-8")
        return output_path
