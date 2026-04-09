"""Unit tests for folder-based batch workflow."""

from pathlib import Path

import pandas as pd

from mle_heatmap_wrapper.core.piece_discovery import PieceDiscovery
from mle_heatmap_wrapper.exporters.csv_exporter import CSVExporter
from mle_heatmap_wrapper.models.data_models import (
    PartConfiguration,
    PieceMetadata,
    ProcessingResult,
)
from mle_heatmap_wrapper.parsers.mlx_parser import MLXParser


def _write_geom_file(path: Path) -> None:
    path.write_text(
        "P X Y Z U V W\n"
        "P -1.0 0.0 10.0 0 0 0\n"
        "P -2.0 1.0 10.5 0 0 0\n"
        "P -3.0 2.0 11.0 0 0 0\n",
        encoding="utf-8",
    )


def _build_config() -> PartConfiguration:
    return PartConfiguration(
        part_number="362",
        supplier="MLX",
        sections_count=2,
        piece_folder_regex=r"^362_.*$",
        folder_metadata_regex=(
            r"^(?P<part_number>\d{3})_.*_(?P<side_token>INT|EXT)_.*_"
            r"(?P<serial_number>[A-Z0-9-]+)_(?P<measurement_date>\d{8})_"
            r"(?P<measurement_time>\d{6})_.*$"
        ),
        supplier_settings={"file_prefix_side_map": {"I": "int", "E": "ext"}},
    )


def test_piece_discovery_filters_piece_names(tmp_path: Path) -> None:
    config = _build_config()
    (tmp_path / "362_VALID_AAA" / "GEOM").mkdir(parents=True)
    (tmp_path / "INVALID_FOLDER" / "GEOM").mkdir(parents=True)

    discovery = PieceDiscovery(config).discover(tmp_path)

    assert len(discovery.discovered) == 1
    assert discovery.discovered[0].name == "362_VALID_AAA"
    assert len(discovery.rejected) == 1


def test_parse_piece_folder_ascii_files(tmp_path: Path) -> None:
    config = _build_config()
    piece_name = "362_850_019_6F9_INT_PC_JE407542-N_05022026_034232_ARCHIVE"
    geom_dir = tmp_path / piece_name / "GEOM"
    geom_dir.mkdir(parents=True)

    _write_geom_file(geom_dir / "I03.MEA")
    _write_geom_file(geom_dir / "E05.MEA")

    parser = MLXParser(config)
    input_data = parser.parse_piece_folder(geom_dir.parent)

    assert len(input_data.dataframe) == 6
    assert set(input_data.dataframe["section_label"].unique()) == {"03", "05"}
    assert set(input_data.dataframe["side"].unique()) == {"int", "ext"}
    assert input_data.piece_metadata is not None
    assert input_data.piece_metadata.serial_number == "JE407542-N"
    assert input_data.piece_metadata.measurement_date == "20260205"


def test_export_piece_results_uses_naming_convention(tmp_path: Path) -> None:
    config = _build_config()
    piece_metadata = PieceMetadata(
        piece_folder_name="any_piece",
        piece_folder_path=str(tmp_path / "any_piece"),
        supplier="MLX",
        part_number="362",
        serial_number="JE407542-N",
        measurement_date="20260205",
    )
    result = ProcessingResult(
        metric_type="widthness",
        data=pd.DataFrame(
            {"section_label": ["03"], "widthness_value": [10.5], "unit": ["mm"]}
        ),
        part_config=config,
        success=True,
        piece_metadata=piece_metadata,
    )

    exporter = CSVExporter(output_dir=tmp_path)
    output_file = exporter.export_piece_results([result], piece_metadata)

    assert output_file.name == "JE407542-N_MLX_362_20260205.csv"
    exported_df = pd.read_csv(output_file)
    assert "metric" in exported_df.columns
    assert exported_df.iloc[0]["serial_number"] == "JE407542-N"
