"""
Unit tests for parsers.
"""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from mle_heatmap_wrapper.parsers.czt_parser import CZTParser
from mle_heatmap_wrapper.parsers.mlx_parser import MLXParser, TECTParser
from mle_heatmap_wrapper.models.data_models import PartConfiguration


@pytest.fixture
def CZT_config():
    """Create CZT test configuration."""
    return PartConfiguration(
        part_number="362", supplier="CZT", sections_count=20
    )


@pytest.fixture
def mlx_config():
    """Create MLX test configuration."""
    return PartConfiguration(
        part_number="362", supplier="MLX", sections_count=27
    )


@pytest.fixture
def sample_csv_data():
    """Create sample CSV data."""
    data = []
    for section in range(5):
        for side in ["int", "ext"]:
            for i in range(20):
                data.append(
                    {
                        "x": 100 + i * 0.1,
                        "y": 200 + i * 0.1,
                        "z": 300 + i * 0.1,
                        "section_label": f"section_{section}",
                        "side": side,
                    }
                )
    return pd.DataFrame(data)


def create_temp_csv(df: pd.DataFrame) -> Path:
    """Create a temporary CSV file."""
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(temp_file.name, index=False)
    return Path(temp_file.name)


class TestCZTParser:
    """Tests for CZT parser."""

    def test_parse_valid_file(self, CZT_config, sample_csv_data):
        """Test parsing a valid CZT file."""
        csv_file = create_temp_csv(sample_csv_data)

        try:
            parser = CZTParser(CZT_config)
            input_data = parser.parse(csv_file)

            assert input_data is not None
            assert len(input_data.dataframe) > 0
            assert input_data.part_config == CZT_config
            assert "CZT" in input_data.metadata["supplier"]
        finally:
            csv_file.unlink()

    def test_parse_with_different_column_names(self, CZT_config):
        """Test parsing with alternative column names."""
        # Create data with alternative column names
        data = {
            "x_coord": [100, 101, 102],
            "y_coord": [200, 201, 202],
            "z_coord": [300, 301, 302],
            "section": ["s1", "s1", "s1"],
            "face": ["int", "ext", "int"],
        }
        df = pd.DataFrame(data)
        csv_file = create_temp_csv(df)

        try:
            parser = CZTParser(CZT_config)
            input_data = parser.parse(csv_file)

            # Should have renamed columns
            assert "x" in input_data.dataframe.columns
            assert "y" in input_data.dataframe.columns
            assert "z" in input_data.dataframe.columns
            assert "section_label" in input_data.dataframe.columns
            assert "side" in input_data.dataframe.columns
        finally:
            csv_file.unlink()

    def test_parse_file_not_found(self, CZT_config):
        """Test parsing with non-existent file."""
        parser = CZTParser(CZT_config)

        with pytest.raises(FileNotFoundError):
            parser.parse(Path("/nonexistent/file.csv"))

    def test_side_conversion(self, CZT_config):
        """Test side notation conversion."""
        data = {
            "x": [100, 101],
            "y": [200, 201],
            "z": [300, 301],
            "section_label": ["s1", "s1"],
            "side": ["intrados", "extrados"],
        }
        df = pd.DataFrame(data)
        csv_file = create_temp_csv(df)

        try:
            parser = CZTParser(CZT_config)
            input_data = parser.parse(csv_file)

            # Should have converted to 'int' and 'ext'
            assert set(input_data.dataframe["side"].unique()) == {"int", "ext"}
        finally:
            csv_file.unlink()


class TestMLXParser:
    """Tests for MLX parser."""

    def test_parse_valid_file(self, mlx_config, sample_csv_data):
        """Test parsing a valid MLX file."""
        csv_file = create_temp_csv(sample_csv_data)

        try:
            parser = MLXParser(mlx_config)
            input_data = parser.parse(csv_file)

            assert input_data is not None
            assert len(input_data.dataframe) > 0
            assert input_data.part_config == mlx_config
            assert "MLX" in input_data.metadata["supplier"]
        finally:
            csv_file.unlink()

    def test_duplicate_removal(self, mlx_config, sample_csv_data):
        """Test that duplicates are removed."""
        # Add duplicates
        df_with_dupes = pd.concat(
            [sample_csv_data, sample_csv_data.head(10)], ignore_index=True
        )

        csv_file = create_temp_csv(df_with_dupes)

        try:
            parser = MLXParser(mlx_config)
            input_data = parser.parse(csv_file)

            # Should have fewer rows after removing duplicates
            assert len(input_data.dataframe) == len(sample_csv_data)
        finally:
            csv_file.unlink()


class TestTECTParser:
    """Tests for TECT PA parser."""

    def test_parse_valid_file(self, sample_csv_data):
        """Test parsing a valid TECT PA file."""
        tect_config = PartConfiguration(
            part_number="362",
            supplier="TECT PA",
            sections_count=27,
        )

        csv_file = create_temp_csv(sample_csv_data)

        try:
            parser = TECTParser(tect_config)
            input_data = parser.parse(csv_file)

            assert input_data is not None
            assert "TECT PA" in input_data.metadata["supplier"]
        finally:
            csv_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
