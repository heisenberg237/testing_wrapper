"""Base parser classes and shared batch-folder ingestion helpers."""

from abc import ABC, abstractmethod
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..core.logger import get_logger
from ..models.data_models import InputData, PartConfiguration, PieceMetadata

logger = get_logger(__name__)


class BaseParser(ABC):
    """Abstract base parser with supplier-specific extension points."""

    _SIDE_MAPPING = {
        "intrados": "int",
        "extrados": "ext",
        "int": "int",
        "ext": "ext",
        "i": "int",
        "e": "ext",
        "inside": "int",
        "outside": "ext",
        "internal": "int",
        "external": "ext",
    }

    def __init__(self, part_config: PartConfiguration):
        self.part_config = part_config
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def parse(self, file_path: Path) -> InputData:
        """Parse one legacy single-file input into InputData."""

    @abstractmethod
    def _validate_file_format(self, df: pd.DataFrame) -> None:
        """Validate supplier file format."""

    def parse_piece_folder(self, piece_folder: Path) -> InputData:
        """Parse one piece folder containing GEOM ASCII files.

        Structure commune: dossier_piece/GEOM/fichiers...
        La logique exacte de lecture des fichiers GEOM est déléguée à
        _parse_geom_folder(), que chaque parser fournisseur peut surcharger.
        """
        if not piece_folder.exists() or not piece_folder.is_dir():
            raise FileNotFoundError(f"Piece directory not found: {piece_folder}")

        # metadata are : serial, supplier, partnumber, measurement date
        piece_metadata = self._extract_piece_metadata(piece_folder)
        geom_folder = piece_folder / self.part_config.geom_folder_name
        if not geom_folder.exists() or not geom_folder.is_dir():
            raise ValueError(
                f"GEOM folder not found in piece directory: {piece_folder}"
            )

        dataframe, geom_info = self._parse_geom_folder(geom_folder, piece_metadata)

        if dataframe.empty:
            raise ValueError(f"No measurement points parsed from: {piece_folder}")

        dataframe = self._post_process_batch_dataframe(dataframe)

        metadata = {
            "supplier": self.part_config.supplier,
            "source_folder": str(piece_folder),
            **geom_info,
        }
        return InputData(
            dataframe=dataframe,
            part_config=self.part_config,
            metadata=metadata,
            piece_metadata=piece_metadata,
        )

    def _parse_geom_folder(
        self, geom_folder: Path, piece_metadata: PieceMetadata
    ) -> Tuple[pd.DataFrame, Dict[str, object]]:
        """Parse GEOM folder contents into a unified DataFrame.

        Méthode surchargeable: chaque parser fournisseur peut implémenter
        sa propre logique selon l'organisation des données (multi-fichiers MEA,
        deux fichiers .xyz avec regroupement par Z, etc.).

        Returns:
            Tuple (DataFrame avec colonnes x,y,z,section_label,side,source_file,
                   dict d'infos pour metadata)
        """
        geom_files = self._list_geom_files(geom_folder)
        
        if not geom_files:
            raise ValueError(f"No GEOM ASCII files found in: {geom_folder}")

        frames: List[pd.DataFrame] = []
        for geom_file in geom_files:
            frame = self._parse_geom_ascii_file(geom_file, piece_metadata)
            if not frame.empty:
                frames.append(frame)

        dataframe = pd.concat(frames, ignore_index=True)
        z_map = self.part_config.nominal.get("sectionlabel_to_znominalcoord_map")
        nominal_list = list(z_map.keys()) if z_map else []

        dataframe = dataframe[
                dataframe["section_label"].astype(str).isin([str(x) for x in nominal_list])
        ]

        geom_info = {
            "geom_files_count": len(geom_files),
            "points_per_file_avg": (
                round(len(dataframe) / len(geom_files), 2) if geom_files else 0
            ),
        }
        return dataframe, geom_info

    def _list_geom_files(self, geom_folder: Path) -> List[Path]:
        allowed_ext = {ext.lower() for ext in self.part_config.geom_file_extensions}
        return [
            path
            for path in sorted(geom_folder.iterdir())
            if path.is_file() and path.suffix.lower() in allowed_ext
        ]

    def _parse_geom_ascii_file(
        self, file_path: Path, piece_metadata: PieceMetadata
    ) -> pd.DataFrame:
        xyz = self._load_ascii_xyz(file_path)
        if xyz.empty:
            return xyz
        
        # legacy-equivalent section extraction
        xyz = self._extract_sections_from_xyz(xyz)

        side = self._extract_side(file_path)
        xyz["side"] = side
        return xyz

    def _extract_side(
        self,
        file_path: Path,
    ) -> Tuple[str, str]:
        stem = file_path.stem
        regex = re.compile(self.part_config.geom_file_regex)
        match = regex.search(stem)

        side = None
        prefix = None

        if match:
            prefix = match.groupdict().get("side_indicator")

        prefix_map = self.part_config.supplier_settings.get(
            "file_prefix_side_map", {}
        )

        if prefix:
            side = prefix_map.get(prefix.upper())
        if not side:
            side = self.part_config.default_side

        return self._normalize_side(side)

    def _extract_sections_from_xyz(self, df: pd.DataFrame, tolerance = 0.5) -> pd.DataFrame:
        """
        Replicates legacy CZT section extraction logic:
        - group by Z nominal
        - keep +/-0.5 mm
        - clamp Z to nominal
        - remove wing points
        """

        if df.empty:
            return df

        z_map = self.part_config.nominal.get('sectionlabel_to_znominalcoord_map')
        
        wing_trim = self.part_config.supplier_settings.get(
            "number_points_end_of_wings_to_delete", 0
        )

        sections = []

        for label, z_nom in z_map.items():
            mask = (df["z"] >= z_nom - tolerance) & (df["z"] <= z_nom + tolerance)
            df_temp = df.loc[mask].copy()

            if df_temp.empty:
                continue

            # force z to nominal (legacy behavior)
            df_temp.loc[:, "z"] = z_nom

            # remove wing points
            if wing_trim > 0 and len(df_temp) > 2 * wing_trim:
                df_temp = df_temp.iloc[wing_trim:-wing_trim]

            df_temp["section_label"] = label
            sections.append(df_temp)

        if not sections:
            return pd.DataFrame(columns=df.columns.tolist() + ["section_label"])

        return pd.concat(sections, ignore_index=True)

    def _extract_piece_metadata(self, piece_folder: Path) -> PieceMetadata:
        name = piece_folder.name
        info: Dict[str, str] = {}

        if self.part_config.folder_metadata_regex:
            folder_match = re.search(self.part_config.folder_metadata_regex, name)
            if folder_match:
                info = {k: v for k, v in folder_match.groupdict().items() if v}

        tokens = [token for token in name.replace("-", "_").split("_") if token]
        serial = info.get("serial_number") or self._guess_serial_number(name, tokens)
        date_token = info.get("measurement_date") or self._guess_date_token(tokens)
        time_token = info.get("measurement_time") or self._guess_time_token(tokens)

        return PieceMetadata(
            piece_folder_name=name,
            piece_folder_path=str(piece_folder),
            supplier=self.part_config.supplier,
            part_number=self.part_config.part_number,
            serial_number=serial,
            measurement_date=self._normalize_measurement_date(date_token),
            measurement_time=self._normalize_measurement_time(time_token),
            extra=info,
        )

    def _guess_serial_number(self, folder_name: str, tokens: List[str]) -> str:
        serial_regex = re.compile(r"\\D{2}\\d{6}(?:-[A-Z0-9]+)?")
        match = serial_regex.search(folder_name.upper())
        if match:
            return match.group(0)
        return "UNKNOWN_SERIAL"

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

    def _normalize_measurement_date(self, raw_date: Optional[str]) -> str:
        if not raw_date:
            return "UNKNOWN_DATE"
        token = raw_date.strip()
        return token

    def _normalize_measurement_time(self, raw_time: Optional[str]) -> str:
        if not raw_time:
            return "UNKNOWN_TIME"
        token = raw_time.strip()
        return token

    def _load_ascii_xyz(self, file_path: Path) -> pd.DataFrame:
        """Load generic ASCII point files and keep first 3 numeric values."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        rows: List[Tuple[float, float, float]] = []
        number_pattern = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if re.search(r"\bX\b", line.upper()) and re.search(
                    r"\bY\b", line.upper()
                ):
                    continue
                numbers = number_pattern.findall(line)
                if len(numbers) < 3:
                    continue
                try:
                    x, y, z = float(numbers[0]), float(numbers[1]), float(numbers[2])
                except ValueError:
                    continue
                rows.append((x, y, z))
        return pd.DataFrame(rows, columns=["x", "y", "z"])

    def _post_process_batch_dataframe(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        cleaned = dataframe.copy()
        cleaned["section_label"] = cleaned["section_label"].astype(str).str.strip()
        cleaned["side"] = cleaned["side"].astype(str).str.lower().str.strip()
        return cleaned

    def _normalize_side(self, side: str) -> str:
        normalized = self._SIDE_MAPPING.get(str(side).strip().lower())
        return normalized or self.part_config.default_side

    def _load_csv(self, file_path: Path, **kwargs) -> pd.DataFrame:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        defaults = {"encoding": "utf-8", "sep": ";"}
        defaults.update(kwargs)
        return pd.read_csv(file_path, **defaults)

    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df.columns = df.columns.str.lower().str.strip()
        return df

    def _convert_side_notation(
        self, df: pd.DataFrame, side_column: str = "side"
    ) -> pd.DataFrame:
        df[side_column] = (
            df[side_column].astype(str).str.lower().str.strip().map(self._SIDE_MAPPING)
        )
        if df[side_column].isna().any():
            df[side_column] = df[side_column].fillna(self.part_config.default_side)
        return df

    def _extract_metadata(self, file_path: Path) -> Dict[str, object]:
        return {
            "source_file": str(file_path),
            "filename": file_path.name,
            "file_size_bytes": file_path.stat().st_size,
        }
    
    def _extract_nominal_sections(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Replicates legacy nominal extraction logic:
        - split by Z nominal
        - +/- 1 mm tolerance
        - clamp Z to nominal
        """

        if df.empty:
            return df
        
        z_map = self.part_config.nominal.get("sectionlabel_to_znominalcoord_map")
        nominal_list = list(z_map.keys()) if z_map else []
        
        df_columns = list(df.columns)
        list_expected =  ["x", "y", "z", "section_label"]

        if not (set(df_columns) - set(list_expected)):
            df = df.dropna(subset=["section_label"]).reset_index(drop=True)
            if nominal_list:
                df = df[
                    df["section_label"].astype(str).isin([str(x) for x in nominal_list])
                ]
            return df
        
        
        tolerance = self.part_config.supplier_settings.get("nominal_z_tolerance", 0.5)

        # ensure first 3 columns are xyz
        df = df.iloc[:, :3].copy()
        df.columns = ["x", "y", "z"]

        sections = []

        for label, z_nom in z_map.items():
            mask = (df["z"] >= z_nom - tolerance) & (df["z"] <= z_nom + tolerance)
            df_temp = df.loc[mask].copy()

            if df_temp.empty:
                continue

            # legacy behavior: force Z to nominal
            df_temp.loc[:, "z"] = z_nom
            df_temp["section_label"] = label

            sections.append(df_temp)

        if not sections:
            return pd.DataFrame(columns=["x", "y", "z", "section_label"])
        
        df_n = pd.concat(sections, ignore_index=True)
        df_n = df_n.dropna(subset=["section_label"]).reset_index(drop=True)
        return df_n

    def parse_nominal(self, file_path: Path) -> Optional[pd.DataFrame]:

        if not file_path.exists():
            return None

        try:
            # detect format
            file_path = Path(str(file_path))
            if file_path.suffix.lower() in [".xls", ".xlsx"]:
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)

            # legacy-equivalent extraction
            df = self._extract_nominal_sections(df)

            if df.empty:
                return None

            return df

        except Exception as exc:
            self.logger.warning(f"Failed to parse nominal file {file_path}: {exc}")
            return None
        
    def parse_nominal_heatmap(self, file_path: Path) -> Optional[pd.DataFrame]:
        if not file_path.exists():
            return None
        try:
            z_map = self.part_config.nominal.get("sectionlabel_to_znominalcoord_map")
            nominal_list = list(z_map.keys()) if z_map else []
            df = self._load_csv(file_path)

            df = df[
                    df["section"].astype(str).isin([str(x) for x in nominal_list])
                ]
            return df
        except Exception as exc:
            self.logger.warning(f"Failed to parse nominal heatmap file {file_path}: {exc}")
            return None
