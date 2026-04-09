"""Part configuration manager loaded from YAML."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from ..core.config import config
from ..core.logger import get_logger
from .data_models import PartConfiguration

logger = get_logger(__name__)


def _normalize_supplier(supplier: str) -> str:
    return str(supplier).strip().upper().replace("_", " ")


class PartConfigManager:
    """Manager for part/supplier configurations."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or config.parts_config_file
        self._configurations: Dict[str, PartConfiguration] = {}
        self._load_configurations()

    def _build_key(self, part_number: str, supplier: str, operation: str) -> str:
        return f"{str(part_number).strip()}_{_normalize_supplier(supplier)}_{operation.strip()}"

    def _load_configurations(self) -> None:
        if not self.config_file.exists():
            logger.warning("Configuration file not found: %s", self.config_file)
            raise ValueError("Configuration file not found: %s", self.config_file)

        with self.config_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        for part_data in data.get("parts", []):
            part_config = PartConfiguration(**part_data)
            self._configurations[part_config.config_key] = part_config
            logger.debug("Loaded configuration: %s", part_config.config_key)

        logger.info("Loaded %s part configurations", len(self._configurations))


    def _save_configurations(self) -> None:
        serializable: List[Dict[str, object]] = []
        for cfg in self._configurations.values():
            serializable.append(
                {
                    "part_number": cfg.part_number,
                    "supplier": cfg.supplier,
                    "operation": cfg.operation,
                    "sections_count": cfg.sections_count,
                    "input_file_pattern": cfg.input_file_pattern,
                    "output_file_pattern": cfg.output_file_pattern,
                    "piece_folder_regex": cfg.piece_folder_regex,
                    "geom_folder_name": cfg.geom_folder_name,
                    "geom_file_extensions": cfg.geom_file_extensions,
                    "geom_file_regex": cfg.geom_file_regex,
                    "folder_metadata_regex": cfg.folder_metadata_regex,
                    "default_side": cfg.default_side,
                    "require_both_sides": cfg.require_both_sides,
                    "strict_section_count": cfg.strict_section_count,
                    "supplier_settings": cfg.supplier_settings,
                    "nominal": cfg.nominal,
                }
            )
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                {"parts": serializable}, handle, allow_unicode=True, sort_keys=False
            )

    def get_configuration(
        self, part_number: str, supplier: str, operation: Optional[str] = 'OP420'
    ) -> Optional[PartConfiguration]:
        return self._configurations.get(self._build_key(part_number, supplier, operation))

    def get_all_configurations(self) -> Dict[str, PartConfiguration]:
        return self._configurations.copy()

    def add_configuration(self, part_config: PartConfiguration) -> None:
        self._configurations[part_config.config_key] = part_config
        self._save_configurations()

    def list_supported_combinations(self) -> List[Tuple[str, str, int]]:
        return sorted(
            [
                (cfg.part_number, cfg.supplier, cfg.sections_count)
                for cfg in self._configurations.values()
            ]
        )
