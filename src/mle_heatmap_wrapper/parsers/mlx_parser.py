"""MLX supplier-specific parsers."""

import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import pandas as pd

from .base_parser import BaseParser
from ..models.data_models import InputData


class MLXParser(BaseParser):
    """Parser for MLX supplier data."""

    def parse(self, file_path: Path) -> InputData:
        df = self._load_csv(file_path)
        df = self._standardize_columns(df)
        self._validate_file_format(df)
        if "side" in df.columns:
            df = self._convert_side_notation(df)
        df = self._apply_mlx_transformations(df)

        metadata = self._extract_metadata(file_path)
        metadata["supplier"] = "MLX"

        return InputData(
            dataframe=df,
            part_config=self.part_config,
            metadata=metadata,
        )
    
    def _normalize_measurement_date(self, raw_date: Optional[str]) -> str:
        if not raw_date:
            return "UNKNOWN_DATE"
        token = raw_date.strip()
        token = datetime.strptime(token, "%d%m%Y").strftime("%Y-%m-%d")
        return token
    
    def _normalize_measurement_time(self, raw_time: Optional[str]) -> str:
        if not raw_time:
            return "UNKNOWN_TIME"
        token = raw_time.strip()
        token = datetime.strptime(token, "%H%M%S").strftime("%H:%M:%S")
        return token
    
    def _guess_date_token(self, tokens: List[str]) -> Optional[str]:
        for token in tokens:
            if re.fullmatch(r"\d{8}", token):
                return token
        return None

    def _guess_time_token(self, tokens: List[str]) -> Optional[str]:
        for token in tokens:
            if re.fullmatch(r"\d{6}", token):
                return token
        return None
    
    def _guess_serial_number(self, folder_name: str, tokens: List[str]) -> str:
        serial_regex = re.compile(r"\\D{2}\\d{6}(?:-[A-Z0-9]+)?")
        match = serial_regex.search(folder_name.upper())
        if match:
            return match.group(0)
        return "UNKNOWN_SERIAL"

    def _validate_file_format(self, df: pd.DataFrame) -> None:
        required_columns = {"x", "y", "z", "section_label", "side"}
        mappings = {
            "x_coordinate": "x",
            "y_coordinate": "y",
            "z_coordinate": "z",
            "section": "section_label",
            "section_number": "section_label",
            "surface_type": "side",
        }
        for old_col, new_col in mappings.items():
            if old_col in df.columns and new_col not in df.columns:
                df.rename(columns={old_col: new_col}, inplace=True)

        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"MLX format missing required columns: {missing}")

    def _apply_mlx_transformations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Make MLX dataframe equivalent to old importSectionsForGenAndTect output.
        """
        # --- ensure numeric ---
        for col in ["x", "y", "z"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # --- remove wing points (same slicing logic as old parser) ---
        if hasattr(self.part_config, "number_points_end_of_wings_to_delete"):
            n = self.part_config.number_points_end_of_wings_to_delete
            if n > 0:
                df = (
                    df.groupby("section_label", group_keys=False)
                    .apply(lambda g: g.iloc[n:-n] if len(g) > 2 * n else g)
                )

        # --- overwrite z with nominal section coordinate ---
        if hasattr(self.part_config, "z_nominal_coord_section"):
            z_map = self.part_config.z_nominal_coord_section

            # section number extraction equivalent to old regex behavior
            df["section_label"] = df["section_label"].astype(str).str.strip()

            def _assign_nominal_z(row):
                section = row["section_label"]
                if section in z_map:
                    return z_map[section]
                return row["z"]

            df["z"] = df.apply(_assign_nominal_z, axis=1)

        # --- drop duplicates (same intent as new parser) ---
        initial_count = len(df)
        df = df.drop_duplicates(subset=["x", "y", "z", "section_label", "side"])
        if len(df) < initial_count:
            self.logger.warning(
                "Removed %s duplicate points", initial_count - len(df)
            )

        # --- ensure float dtype exactly like old numpy conversion ---
        df[["x", "y", "z"]] = df[["x", "y", "z"]].astype(float)

        # --- reset index for clean dataframe ---
        df = df.reset_index(drop=True)

        return df

