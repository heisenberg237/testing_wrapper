"""Tests for XYZFolderParser (two-file format, group by Z)."""

from pathlib import Path

import pytest

from mle_heatmap_wrapper.models.data_models import PartConfiguration
from mle_heatmap_wrapper.parsers.xyz_parser import XYZFolderParser


def _build_config() -> PartConfiguration:
    return PartConfiguration(
        part_number="362",
        supplier="XYZ_SUPPLIER",
        sections_count=3,
        piece_folder_regex=r"^362_.*$",
        geom_folder_name="GEOM",
        geom_file_extensions=[".xyz"],
        supplier_settings={"z_grouping_tolerance": 0.1},
    )


def test_parse_piece_folder_xyz_format(tmp_path: Path) -> None:
    """Test XYZ format: int.xyz + ext.xyz, sections from Z grouping."""
    geom_dir = tmp_path / "362_TEST_XYZ" / "GEOM"
    geom_dir.mkdir(parents=True)

    # int.xyz: points at Z=10 and Z=20
    int_content = (
        "1.0 2.0 10.0\n"
        "2.0 3.0 10.0\n"
        "3.0 4.0 10.0\n"
        "4.0 5.0 20.0\n"
        "5.0 6.0 20.0\n"
    )
    (geom_dir / "int.xyz").write_text(int_content)

    # ext.xyz: points at Z=10, 20, 30
    ext_content = (
        "1.1 2.1 10.0\n"
        "2.1 3.1 10.0\n"
        "4.1 5.1 20.0\n"
        "7.0 8.0 30.0\n"
    )
    (geom_dir / "ext.xyz").write_text(ext_content)

    config = _build_config()
    parser = XYZFolderParser(config)
    input_data = parser.parse_piece_folder(geom_dir.parent)

    assert len(input_data.dataframe) == 9
    assert set(input_data.dataframe["side"].unique()) == {"int", "ext"}
    # Sections: 01, 02, 03 from Z grouping
    sections = input_data.dataframe["section_label"].unique()
    assert len(sections) >= 2

    int_points = input_data.dataframe[input_data.dataframe["side"] == "int"]
    assert len(int_points) == 5
    ext_points = input_data.dataframe[input_data.dataframe["side"] == "ext"]
    assert len(ext_points) == 4


def test_parse_piece_folder_xyz_single_file(tmp_path: Path) -> None:
    """Test with only int.xyz (no ext)."""
    geom_dir = tmp_path / "362_SINGLE" / "GEOM"
    geom_dir.mkdir(parents=True)
    (geom_dir / "int.xyz").write_text("1 2 10\n2 3 10\n3 4 20\n")

    config = _build_config()
    parser = XYZFolderParser(config)
    input_data = parser.parse_piece_folder(geom_dir.parent)

    assert len(input_data.dataframe) == 3
    assert set(input_data.dataframe["side"].unique()) == {"int"}


def test_parse_legacy_raises(tmp_path: Path) -> None:
    """XYZ parser does not support single-file mode."""
    config = _build_config()
    parser = XYZFolderParser(config)

    with pytest.raises(NotImplementedError, match="batch mode"):
        parser.parse(tmp_path / "dummy.csv")


def test_parse_piece_folder_xyz_with_z_to_cr_map(tmp_path: Path) -> None:
    """Test XYZ format with z_to_cr_map: Z values map to specific CR labels."""
    geom_dir = tmp_path / "362_MAPPED" / "GEOM"
    geom_dir.mkdir(parents=True)

    # Points at Z=10.0 and Z=20.0 - map to CR "03" and "05"
    (geom_dir / "int.xyz").write_text(
        "1.0 2.0 10.0\n2.0 3.0 10.0\n4.0 5.0 20.0\n"
    )
    (geom_dir / "ext.xyz").write_text(
        "1.1 2.1 10.0\n4.1 5.1 20.0\n"
    )

    config = PartConfiguration(
        part_number="362",
        supplier="XYZ_MAPPED",
        sections_count=2,
        piece_folder_regex=r"^362_.*$",
        geom_folder_name="GEOM",
        geom_file_extensions=[".xyz"],
        supplier_settings={
            "z_to_cr_map": {"10.0": "03", "20.0": "05"},
            "z_grouping_tolerance": 0.1,
        },
    )
    parser = XYZFolderParser(config)
    input_data = parser.parse_piece_folder(geom_dir.parent)

    assert set(input_data.dataframe["section_label"].unique()) == {"03", "05"}
    int_at_10 = input_data.dataframe[
        (input_data.dataframe["side"] == "int") & (input_data.dataframe["z"] == 10.0)
    ]
    assert all(int_at_10["section_label"] == "03")
    int_at_20 = input_data.dataframe[
        (input_data.dataframe["side"] == "int") & (input_data.dataframe["z"] == 20.0)
    ]
    assert all(int_at_20["section_label"] == "05")
