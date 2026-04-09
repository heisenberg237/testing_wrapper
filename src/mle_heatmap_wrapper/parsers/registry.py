"""Parser registry: mapping supplier -> parser class for extensibility."""

from typing import Dict, Optional, Type

from .base_parser import BaseParser
from .czt_parser import CZTParser
from .mlx_parser import MLXParser
from .agb_parser import AGBParser
from .tect_parser import TECTParser
from .xyz_parser import XYZFolderParser

# Default registry: parser class name -> class
PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    "CZTParser": CZTParser,
    "MLXParser": MLXParser,
    "TECTParser": TECTParser,
    "AGBParser": AGBParser,
    "XYZFolderParser": XYZFolderParser,
}


def get_parser_class(
    name: str,
    override_from_registry: Optional[Dict[str, Type[BaseParser]]] = None,
) -> Type[BaseParser]:
    """Resolve parser class by name."""
    registry = override_from_registry or PARSER_REGISTRY
    cls = registry.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown parser: {name}. Registered: {list(registry.keys())}"
        )
    return cls


def register_parser(name: str, parser_class: Type[BaseParser]) -> None:
    """Register a parser class for extensibility."""
    PARSER_REGISTRY[name] = parser_class
