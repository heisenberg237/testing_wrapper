"""Data models used by the MLE heatmap wrapper."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

import pandas as pd


class PartNumber(Enum):
    """Supported part numbers."""

    PN_362_1A = "362-850-019"
    PN_364_1B = "364-850-019"


class Supplier(Enum):
    """Supported suppliers."""

    CZT = "CZT"
    MLX = "MLX"
    TECT = "TECT"
    AGB = "AGB"


class MetricType(Enum):
    """Types of geometric metrics."""

    WIDTHNESS = "widthness"
    TANGENT = "tangent"
    CHORDS = "chords"
    THICKNESS = "thickness"
    WAVENESS = "waveness"


@dataclass
class PartConfiguration:
    """Configuration for a specific part/supplier processing mode."""

    part_number: str
    supplier: str
    operation: str
    mletracking: str
    sections_count: int

    input_file_pattern: str = ""
    output_file_pattern: str = "{serial_number}_{supplier}_{part_number}_{operation}_{metric}.csv"

    piece_folder_regex: str = ".*"
    sn_full_regex: str = r"(?P<sn>\D\D\d\d\d\d\d\d-[A-Z0-9]{1})"
    geom_folder_name: str = "GEOM"
    geom_file_extensions: List[str] = field(default_factory=lambda: [".mea", ".xyz"])
    geom_file_regex: str = r"(?P<section_prefix>[A-Za-z]?)(?P<section>\d+)"
    folder_metadata_regex: Optional[str] = None
    default_side: str = "int"
    require_both_sides: bool = False
    strict_section_count: bool = True

    supplier_settings: Dict[str, Any] = field(default_factory=dict)
    nominal: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sections_count <= 0:
            raise ValueError("sections_count must be positive")
        self.part_number = str(self.part_number).strip()
        self.supplier = str(self.supplier).strip()
        if self.default_side not in {"int", "ext"}:
            raise ValueError("default_side must be either 'int' or 'ext'")
        self.geom_file_extensions = [
            ext if ext.startswith(".") else f".{ext}"
            for ext in self.geom_file_extensions
        ]

    @property
    def normalized_supplier(self) -> str:
        return self.supplier.upper().replace("_", " ")

    @property
    def config_key(self) -> str:
        return f"{self.part_number}_{self.normalized_supplier}_{self.operation}"

    def get_output_filename(self, metric: str, serial_number:str) -> str:
        return self.output_file_pattern.format(
            serial_number=serial_number,
            supplier=self.supplier.replace(" ", "_"),
            part_number=self.part_number,
            operation=self.operation,
            metric=metric,
        )

    def get_z_to_cr_map(self) -> Optional[Dict[float, str]]:
        """Retourne le mapping Z → label CR depuis supplier_settings.

        Format attendu: { "281.1": "03", "285.2": "05", ... }
        Les clés YAML (string) sont converties en float.
        """
        raw = self.supplier_settings.get("z_to_cr_map")
        if not raw or not isinstance(raw, dict):
            return None
        result: Dict[float, str] = {}
        for k, v in raw.items():
            try:
                result[float(k)] = str(v).strip()
            except (ValueError, TypeError):
                continue
        return result if result else None


@dataclass
class PieceMetadata:
    """Metadata resolved from a piece directory and GEOM files."""

    piece_folder_name: str
    piece_folder_path: str
    supplier: str
    part_number: str
    serial_number: str = "UNKNOWN_SERIAL"
    measurement_date: str = "UNKNOWN_DATE"
    measurement_time: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_supplier(self) -> str:
        return self.supplier.upper().replace(" ", "_")
    
    @property
    def datetimestamp(self) -> datetime:
        if not self.measurement_date or self.measurement_date == "UNKNOWN_DATE":
            return None
        try:
            if self.measurement_time:
                return datetime.fromisoformat(
                    f"{self.measurement_date} {self.measurement_time}"
                )
            return datetime.fromisoformat(self.measurement_date)
        except Exception:
            return None
    
    @property
    def serial_number_short(self) -> str:
        return self.serial_number.upper().split("-")[0]


@dataclass
class InputData:
    """Container for parsed measurement data."""

    dataframe: pd.DataFrame
    part_config: PartConfiguration
    nominal_sections: Optional[pd.DataFrame] = None
    nominal_skeleton: Optional[pd.DataFrame] = None
    nominal_heatmap_widthness: Optional[pd.DataFrame] = None
    nominal_heatmap_thickness_intrados: Optional[pd.DataFrame] = None
    nominal_heatmap_thickness_extrados: Optional[pd.DataFrame] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    piece_metadata: Optional[PieceMetadata] = None

    def __post_init__(self) -> None:
        required_columns = {"x", "y", "z", "section_label", "side"}
        if not required_columns.issubset(self.dataframe.columns):
            missing = required_columns - set(self.dataframe.columns)
            raise ValueError(f"Missing required columns: {missing}")

        valid_sides = {"int", "ext"}
        invalid_sides = set(self.dataframe["side"].dropna().unique()) - valid_sides
        if invalid_sides:
            raise ValueError(
                f"Invalid side values: {invalid_sides}. Must be 'int' or 'ext'"
            )

    @property
    def sections(self) -> List[Any]:
        return sorted(self.dataframe["section_label"].unique())

    @property
    def points_count(self) -> int:
        return len(self.dataframe)

    @property
    def sections_count(self) -> int:
        return len(self.sections)


@dataclass
class ProcessingResult:
    """Result produced by one metric calculation."""

    metric_type: str
    data: pd.DataFrame
    part_config: PartConfiguration
    success: bool = True
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    processing_time_seconds: float = 0.0
    piece_metadata: Optional[PieceMetadata] = None

    @property
    def rows_count(self) -> int:
        return len(self.data) if self.data is not None else 0


@dataclass
class ValidationResult:
    """Result from input data validation."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sections_validated: int = 0
    sections_expected: int = 0

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def get_summary(self) -> str:
        lines = [
            f"Validation Result: {'PASS' if self.is_valid else 'FAIL'}",
            f"Sections: {self.sections_validated}/{self.sections_expected}",
        ]
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  - {error}")
        if self.warnings:
            lines.append(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        return "\n".join(lines)
