"""Suppliers configuration: aliases, parser mapping, side tokens."""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .config import config
from .logger import get_logger

logger = get_logger(__name__)


class SuppliersConfig:
    """Load and resolve supplier aliases / parser mapping from suppliers_config.yaml."""

    _instance: Optional["SuppliersConfig"] = None

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or config.suppliers_config_file
        self._aliases: Dict[str, str] = {}  # alias -> canonical name
        self._parser_map: Dict[str, str] = {}  # canonical -> parser class name
        self._load()

    def _load(self) -> None:
        if not self.config_file.exists():
            logger.debug("Suppliers config not found: %s", self.config_file)
            return
        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for canonical, supp_data in data.get("suppliers", {}).items():
                if not isinstance(supp_data, dict):
                    continue
                canonical = str(canonical).strip()
                self._aliases[canonical.upper().replace("_", " ")] = canonical
                for alias in supp_data.get("aliases", []):
                    key = str(alias).strip().upper().replace("_", " ")
                    self._aliases[key] = canonical
                parser_cls = supp_data.get("parser_class")
                if parser_cls:
                    self._parser_map[canonical] = str(parser_cls)
        except Exception as exc:
            logger.warning("Failed to load suppliers config: %s", exc)

    def resolve_supplier(self, name: str) -> str:
        """Normalize supplier name via aliases (e.g. TECT_PA -> TECT PA)."""
        key = str(name).strip().upper().replace("_", " ")
        return self._aliases.get(key, key)

    def get_parser_class_name(self, supplier: str) -> Optional[str]:
        """Return parser class name from config if defined."""
        canonical = self.resolve_supplier(supplier)
        return self._parser_map.get(canonical)


def get_suppliers_config() -> SuppliersConfig:
    if SuppliersConfig._instance is None:
        SuppliersConfig._instance = SuppliersConfig()
    return SuppliersConfig._instance
