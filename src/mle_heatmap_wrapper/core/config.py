"""Application configuration objects."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# COLLECTION_MAPPING = {
#     "waveness": "widthness_test",
#     "thickness": "widthness_test",
#     "widthness": "widthness_test",
#     "chord": "widthness_test",
#     "tangent": "widthness_test",
# }

COLLECTION_MAPPING = {
    "waveness": "waveness",
    "thickness": "thickness",
    "widthness": "widthness",
    "chord": "chord",
    "tangent": "tangent",
}

SIDE_MAPPING = {
    "int": "intrados",
    "ext": "extrados",
    "both": "both",
}

SERIAL_REGEX = r""

def _resolve_base_dir() -> Path:
    """Resolve project root: env MLE_PROJECT_ROOT or parents from this file."""
    env_root = os.getenv("MLE_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    # config.py is in src/mle_heatmap_wrapper/core/ -> parents[3] = project root
    return Path(__file__).resolve().parents[3]


def _ensure_dir(path: Path) -> None:
    """Create directory; log warning if failed (e.g. read-only env, tests)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # non-fatal: e.g. tests with CONFIG_DIR, read-only env


@dataclass
class PathConfig:
    """Filesystem paths used by the application."""

    base_dir: Path = field(default_factory=_resolve_base_dir)
    config_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    output_dir: Path = field(init=False)
    temp_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        env_config = os.getenv("MLE_CONFIG_DIR")
        self.config_dir = Path(env_config) if env_config else self.base_dir / "config"
        self.logs_dir = self.base_dir / "logs"
        self.output_dir = Path(
            os.getenv("OUTPUT_DIR", str(self.base_dir / "output"))
        )
        self.temp_dir = Path(os.getenv("TEMP_DIR", str(self.base_dir / "temp")))

        for directory in (self.logs_dir, self.output_dir, self.temp_dir):
            _ensure_dir(directory)


@dataclass
class LoggingConfig:
    """Logging settings."""

    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    file_rotation: str = "midnight"
    backup_count: int = 30
    console_output: bool = field(
        default_factory=lambda: os.getenv("CONSOLE_LOG", "true").lower() == "true"
    )


@dataclass
class ProcessingConfig:
    """Processing options."""

    enable_op_data: bool = field(
        default_factory=lambda: os.getenv("ENABLE_OP_DATA", "false").lower() == "true"
    )
    section_tolerance: float = 0.1
    min_points_per_section: int = 10
    enable_notifications: bool = field(
        default_factory=lambda: os.getenv("ENABLE_NOTIFICATIONS", "false").lower()
        == "true"
    )
    notification_email: Optional[str] = field(
        default_factory=lambda: os.getenv("NOTIFICATION_EMAIL")
    )


@dataclass
class MongoConfig:
    """MongoDB options for ETL compatibility hooks."""
    uri : str = field(default_factory=lambda: os.getenv("MONGO_URI", ""))
    database: str = field(default_factory=lambda: os.getenv("MONGO_DB_MLEHEATMAP", "mleHeatmap"))
    database_mledata: str = field(default_factory=lambda: os.getenv("MONGO_DB_MLEDATA", "mleData"))
    collection_mletracking: str = field(
        default_factory=lambda: os.getenv("MONGO_COLLECTION_MLEDATA", "mleTracking")
    )


class Config:
    """Global configuration aggregate."""

    def __init__(self):
        self.paths = PathConfig()
        self.logging = LoggingConfig()
        self.processing = ProcessingConfig()
        self.mongo = MongoConfig()

    @property
    def parts_config_file(self) -> Path:
        return self.paths.config_dir / "parts_config.yaml"

    @property
    def suppliers_config_file(self) -> Path:
        return self.paths.config_dir / "suppliers_config.yaml"


config = Config()
