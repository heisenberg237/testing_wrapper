"""Data validator for MLE heatmap inputs."""

import numpy as np

from ..core.config import config
from ..core.logger import get_logger
from ..models.data_models import InputData, PartConfiguration, ValidationResult

logger = get_logger(__name__)


class DataValidator:
    """Validator for input data quality and consistency."""

    def __init__(self, part_config: PartConfiguration):
        self.part_config = part_config
        self.logger = get_logger(self.__class__.__name__)

    def validate(self, input_data: InputData) -> ValidationResult:
        result = ValidationResult(
            is_valid=True,
            sections_expected=self.part_config.sections_count,
        )
        self._validate_sections_count(input_data, result)
        self._validate_sections_completeness(input_data, result)
        self._validate_point_distribution(input_data, result)
        self._validate_coordinate_ranges(input_data, result)
        self._validate_side_coverage(input_data, result)
        self._validate_data_quality(input_data, result)
        result.sections_validated = input_data.sections_count
        return result

    def _validate_sections_count(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        actual = input_data.sections_count
        expected = self.part_config.sections_count
        if actual == expected:
            return
        tolerance = config.processing.section_tolerance
        diff = abs(actual - expected)
        if diff > tolerance * expected and self.part_config.strict_section_count:
            result.add_error(
                f"Section count mismatch: found {actual}, expected {expected} (±{tolerance*100:.0f}%)"
            )
        else:
            result.add_warning(
                f"Section count slightly off: found {actual}, expected {expected}"
            )

    def _validate_sections_completeness(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        df = input_data.dataframe
        min_points = config.processing.min_points_per_section
        section_counts = df.groupby("section_label").size()
        incomplete = section_counts[section_counts < min_points]
        if len(incomplete) > 0:
            result.add_warning(
                f"Found {len(incomplete)} sections with fewer than {min_points} points: "
                f"{list(incomplete.index)}"
            )

        # Guard against sparse points on one side even when total section points look acceptable.
        side_counts = df.groupby(["section_label", "side"]).size()
        sparse_sides = side_counts[side_counts < min_points]
        if len(sparse_sides) > 0:
            sample = [f"{section}/{side}" for section, side in sparse_sides.index[:5]]
            result.add_warning(
                f"Found {len(sparse_sides)} sparse section-side groups (<{min_points} points): "
                f"{sample}{'...' if len(sparse_sides) > 5 else ''}"
            )

    def _validate_point_distribution(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        section_counts = input_data.dataframe.groupby("section_label").size()
        mean_count = section_counts.mean()
        std_count = section_counts.std()
        if mean_count > 0 and std_count > mean_count * 0.5:
            result.add_warning(
                f"High variability in points per section (mean: {mean_count:.1f}, std: {std_count:.1f})"
            )

    def _validate_coordinate_ranges(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        df = input_data.dataframe
        for coord in ("x", "y", "z"):
            if df[coord].isna().any():
                result.add_error(
                    f"Found {int(df[coord].isna().sum())} NaN values in {coord} coordinate"
                )
            if np.isinf(df[coord]).any():
                result.add_error(
                    f"Found {int(np.isinf(df[coord]).sum())} infinite values in {coord} coordinate"
                )
            if df[coord].std() == 0:
                result.add_error(
                    f"Zero variance in {coord} coordinate - all points identical"
                )

    def _validate_side_coverage(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        df = input_data.dataframe
        require_both = self.part_config.require_both_sides
        side_counts = df["side"].value_counts()

        if "int" not in side_counts:
            if require_both:
                result.add_error("No intrados points found in data")
            else:
                result.add_warning("No intrados points found in data")
        if "ext" not in side_counts:
            if require_both:
                result.add_error("No extrados points found in data")
            else:
                result.add_warning("No extrados points found in data")

        missing = []
        for section in input_data.sections:
            section_data = df[df["section_label"] == section]
            if set(section_data["side"].unique()) != {"int", "ext"}:
                missing.append(section)
        if missing:
            message = (
                f"Found {len(missing)} sections without both int/ext sides: "
                f"{missing[:5]}{'...' if len(missing) > 5 else ''}"
            )
            if require_both:
                result.add_error(message)
            else:
                result.add_warning(message)

    def _validate_data_quality(
        self, input_data: InputData, result: ValidationResult
    ) -> None:
        df = input_data.dataframe
        duplicates = df.duplicated(subset=["x", "y", "z", "section_label", "side"])
        if duplicates.any():
            result.add_warning(f"Found {int(duplicates.sum())} duplicate points")


def validate_input_data(input_data: InputData) -> ValidationResult:
    """Convenience function for validation."""

    validator = DataValidator(input_data.part_config)
    return validator.validate(input_data)
