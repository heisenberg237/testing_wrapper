"""Parser pour format GEOM alternatif: deux fichiers .xyz (int/ext), regroupement par Z.

Exemple de structure GEOM:
    GEOM/
    ├── int.xyz   # Tous points intrados, toutes sections
    └── ext.xyz   # Tous points extrados, toutes sections

Les sections (CR) sont définies en regroupant les points ayant un Z identique
ou approximativement identique (tolérance configurable).
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .base_parser import BaseParser
from ..models.data_models import InputData, PieceMetadata


class XYZFolderParser(BaseParser):
    """Parser pour format: deux fichiers .xyz, regroupement par Z pour les sections.

    Utilisez ce parser comme base pour les fournisseurs dont les données
    sont organisées en un fichier int.xyz et un fichier ext.xyz contenant
    tous les points à tous les Z. Les sections (CR) sont déduites par
    regroupement des points selon leur coordonnée Z.
    """

    # Noms de fichiers attendus dans GEOM (à surcharger si nécessaire)
    INT_FILE_NAMES = ("int.xyz", "INT.xyz", "intrados.xyz")
    EXT_FILE_NAMES = ("ext.xyz", "EXT.xyz", "extrados.xyz")

    # Tolérance pour considérer deux Z comme identiques (mm)
    Z_TOLERANCE_DEFAULT = 0.01

    def parse(self, file_path: Path) -> InputData:
        """Mode legacy non supporté pour ce format (dossier GEOM uniquement)."""
        raise NotImplementedError(
            "XYZFolderParser supports only batch mode (parse_piece_folder). "
            "Single-file mode not applicable for int.xyz/ext.xyz format."
        )

    def _validate_file_format(self, df: pd.DataFrame) -> None:
        """Validation minimale pour format XYZ."""
        required = {"x", "y", "z"}
        if not required.issubset(df.columns):
            raise ValueError(
                f"XYZ format requires columns {required}, got {set(df.columns)}"
            )

    def _parse_geom_folder(
        self, geom_folder: Path, piece_metadata: PieceMetadata
    ) -> Tuple[pd.DataFrame, Dict[str, object]]:
        """Lit int.xyz et ext.xyz, regroupe par Z pour former les sections."""
        int_file = self._find_file(geom_folder, self.INT_FILE_NAMES)
        ext_file = self._find_file(geom_folder, self.EXT_FILE_NAMES)

        if not int_file and not ext_file:
            raise ValueError(
                f"No int.xyz or ext.xyz found in {geom_folder}. "
                "Expected int.xyz and/or ext.xyz."
            )

        frames: List[pd.DataFrame] = []
        files_found = 0

        z_tolerance = self.part_config.supplier_settings.get(
            "z_grouping_tolerance", self.Z_TOLERANCE_DEFAULT
        )

        if int_file:
            df_int = self._load_and_group_by_z(int_file, "int", z_tolerance)
            if not df_int.empty:
                frames.append(df_int)
                files_found += 1

        if ext_file:
            df_ext = self._load_and_group_by_z(ext_file, "ext", z_tolerance)
            if not df_ext.empty:
                frames.append(df_ext)
                files_found += 1

        if not frames:
            raise ValueError(f"No points parsed from {geom_folder}")

        dataframe = pd.concat(frames, ignore_index=True)
        geom_info = {
            "geom_files_count": files_found,
            "points_per_file_avg": (
                round(len(dataframe) / files_found, 2) if files_found else 0
            ),
        }
        return dataframe, geom_info

    def _find_file(
        self, folder: Path, names: Tuple[str, ...]
    ) -> Optional[Path]:
        """Find first existing file with given names in folder."""
        for name in names:
            path = folder / name
            if path.exists() and path.is_file():
                return path
        return None

    def _load_and_group_by_z(
        self, file_path: Path, side: str, z_tolerance: float
    ) -> pd.DataFrame:
        """Load XYZ file and assign section_label from Z.

        Si z_to_cr_map est défini dans supplier_settings, on utilise le mapping
        Z → CR pour assigner les sections. Sinon, regroupement auto par Z.
        """
        xyz = self._load_ascii_xyz(file_path)
        if xyz.empty:
            return xyz

        xyz["side"] = self._normalize_side(side)
        xyz["source_file"] = file_path.name

        z_to_cr = self.part_config.get_z_to_cr_map()
        if z_to_cr:
            xyz["section_label"] = xyz["z"].apply(
                lambda z: self._resolve_cr_from_z(z, z_to_cr, z_tolerance)
            )
        else:
            z_rounded = (
                np.round(xyz["z"] / z_tolerance) * z_tolerance
            ).values
            unique_z = sorted(pd.Series(z_rounded).unique())
            label_map = {z: str(i + 1).zfill(2) for i, z in enumerate(unique_z)}
            xyz["section_label"] = pd.Series(z_rounded).map(label_map)

        return xyz[["x", "y", "z", "section_label", "side", "source_file"]]

    def _resolve_cr_from_z(
        self, z: float, z_to_cr_map: Dict[float, str], tolerance: float
    ) -> str:
        """Associe une coordonnée Z au label CR le plus proche (dans la tolérance)."""
        if not z_to_cr_map:
            return "00"
        best_cr = None
        best_dist = float("inf")
        for config_z, cr_label in z_to_cr_map.items():
            dist = abs(z - config_z)
            if dist < best_dist:
                best_dist = dist
                best_cr = cr_label
        if best_cr is not None and best_dist <= tolerance:
            return best_cr
        if best_cr is not None:
            self.logger.debug(
                "Z=%.3f assigned to CR %s (dist=%.4f > tolerance=%.4f)",
                z,
                best_cr,
                best_dist,
                tolerance,
            )
            return best_cr
        return "00"
