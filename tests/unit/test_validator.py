"""
Unit tests for DataValidator.
"""

import pytest
import pandas as pd
import numpy as np

from mle_heatmap_wrapper.validators.data_validator import DataValidator
from mle_heatmap_wrapper.models.data_models import PartConfiguration, InputData


@pytest.fixture
def part_config():
    """Create a test part configuration."""
    return PartConfiguration(
        part_number="362", supplier="CZT", sections_count=20
    )


@pytest.fixture
def valid_dataframe():
    """Create a valid test DataFrame."""
    sections = [f"section_{i}" for i in range(20)]
    data = []

    for section in sections:
        # Add intrados points
        for i in range(50):
            data.append(
                {
                    "x": 100 + i * 0.1,
                    "y": 200 + i * 0.1,
                    "z": 300 + i * 0.1,
                    "section_label": section,
                    "side": "int",
                }
            )
        # Add extrados points
        for i in range(50):
            data.append(
                {
                    "x": 100 + i * 0.1,
                    "y": 200 + i * 0.1,
                    "z": 300 + i * 0.1 + 10,  # Offset for extrados
                    "section_label": section,
                    "side": "ext",
                }
            )

    return pd.DataFrame(data)


class TestDataValidator:
    """Tests for DataValidator class."""

    def test_valid_data_passes(self, part_config, valid_dataframe):
        """Test that valid data passes validation."""
        input_data = InputData(dataframe=valid_dataframe, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        assert result.is_valid
        assert len(result.errors) == 0
        assert result.sections_validated == 20

    def test_section_count_mismatch(self, part_config, valid_dataframe):
        """Test validation fails with wrong section count."""
        # Remove some sections
        df = valid_dataframe[
            valid_dataframe["section_label"].isin([f"section_{i}" for i in range(15)])
        ]

        input_data = InputData(dataframe=df, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        assert not result.is_valid
        assert any("Section count" in err for err in result.errors)

    def test_missing_side_detected(self, part_config, valid_dataframe):
        """Test that missing side (int/ext) is detected."""
        # Remove all extrados points from one section
        df = valid_dataframe.copy()
        df = df[~((df["section_label"] == "section_0") & (df["side"] == "ext"))]

        input_data = InputData(dataframe=df, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        # Should have warnings about missing sides
        assert len(result.warnings) > 0
        assert any("side" in str(w).lower() for w in result.warnings)

    def test_nan_coordinates_detected(self, part_config, valid_dataframe):
        """Test that NaN coordinates are detected."""
        df = valid_dataframe.copy()
        df.loc[0:10, "x"] = np.nan

        input_data = InputData(dataframe=df, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        assert not result.is_valid
        assert any("NaN" in err for err in result.errors)

    def test_duplicate_points_warning(self, part_config, valid_dataframe):
        """Test that duplicate points generate a warning."""
        df = valid_dataframe.copy()
        # Add duplicate rows
        duplicates = df.head(10).copy()
        df = pd.concat([df, duplicates], ignore_index=True)

        input_data = InputData(dataframe=df, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        assert len(result.warnings) > 0
        assert any("duplicate" in str(w).lower() for w in result.warnings)

    def test_insufficient_points_warning(self, part_config):
        """Test warning for sections with few points."""
        # Create data with very few points per section
        data = []
        for i in range(20):
            for side in ["int", "ext"]:
                for j in range(5):  # Only 5 points per side
                    data.append(
                        {
                            "x": 100 + j,
                            "y": 200 + j,
                            "z": 300 + j,
                            "section_label": f"section_{i}",
                            "side": side,
                        }
                    )

        df = pd.DataFrame(data)
        input_data = InputData(dataframe=df, part_config=part_config)

        validator = DataValidator(part_config)
        result = validator.validate(input_data)

        # Should warn about insufficient points
        assert len(result.warnings) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
