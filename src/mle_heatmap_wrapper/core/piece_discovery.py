"""Piece folder discovery utilities for batch execution mode."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import List, Tuple, Dict
from collections import defaultdict

from ..core.logger import get_logger
from ..models.data_models import PartConfiguration
from ..core.mongo_helpers import create_mongo_client
from ..core.config import MongoConfig
from ..core.config import COLLECTION_MAPPING

logger = get_logger(__name__)


@dataclass
class DiscoveryResult:
    """Container for discovered and rejected piece folders."""
    discovered: Dict[str, List[Path]] = field(default_factory=lambda: defaultdict(list))
    rejected: Dict[str, List[Path]] = field(default_factory=lambda: defaultdict(list))


class PieceDiscovery:
    """Discover piece folders containing GEOM files from an input root."""

    def __init__(self, part_config: PartConfiguration, metric_characs: List[str]):
        self.part_config = part_config
        self._piece_regex = re.compile(part_config.piece_folder_regex)
        self._sn_full_regex = re.compile(part_config.sn_full_regex)
        self.logger = get_logger(self.__class__.__name__)
        self.mongo = create_mongo_client(MongoConfig().uri)
        self.metric_characs = metric_characs

        # DB handles
        self.db_tracking = self.mongo[MongoConfig().database_mledata][self.part_config.mletracking]
        self.db_heatmap = self.mongo[MongoConfig().database]

    def _normalize_sn(self, sn: str) -> str:
        return sn.split("-")[0] if sn else None


    def _resolve_collection(self, metric_type: str):
        """
        Resolve Mongo collection from metric type.
        """

        metric = metric_type.lower()
        collection_name = COLLECTION_MAPPING.get(metric, metric)

        return self.db_heatmap[collection_name]
    
    def _get_tracking_serials(self):

        if self.part_config.mletracking == "mleTracking":
            query = {
                "supplier": self.part_config.supplier,
                "pn": {
                    "$regex": f"^{self.part_config.part_number}",
                    "$options": "i",
                },
                "checkGeom": 1,
            }
            # check if collection has any document with 'op'
            has_op = self.db_tracking.find_one({"op": {"$exists": True}}) is not None

            if has_op:
                query["op"] = self.part_config.operation

        elif self.part_config.mletracking == "bayTracking":
            query = {
                "op" : self.part_config.operation
            }

        cursor = self.db_tracking.find(query, {"sn": 1})
        
        return {
            self._normalize_sn(doc["sn"])
            for doc in cursor
            if doc.get("sn")
        }
    
    def _get_processed_serials(self, charac: str):

        collection = self._resolve_collection(charac)

        cursor =  collection.find(
            {
                "supplier": self.part_config.supplier,
                "partNumber": {"$regex": f"^{self.part_config.part_number}", "$options":"i"},
                "operation": self.part_config.operation
            },
            {"serial": 1},
        )
        return {
            self._normalize_sn(doc.get("serial"))
            for doc in cursor
            if doc.get("serial")
        }
    
    def discover(self, input_root: Path) -> DiscoveryResult:
        """
        Discover piece folders recursively from the input root.

        Any directory that owns a `GEOM` sub-directory can be considered a piece
        candidate. A supplier/part regex can then accept/reject it.
        """
        if not input_root.exists() or not input_root.is_dir():
            raise FileNotFoundError(f"Input directory not found: {input_root}")

        geom_name = self.part_config.geom_folder_name
        result = DiscoveryResult()
        seen = set()
        fs_pieces = defaultdict(list)

        # Step 1: DB filtering
        tracking_sn = self._get_tracking_serials()

        for geom_dir in input_root.rglob(geom_name):
            if not geom_dir.is_dir():
                continue

            piece_dir = geom_dir.parent
            if piece_dir in seen:
                continue
            seen.add(piece_dir)

            if not self._piece_regex.search(piece_dir.name):
                result.rejected['all'].append(
                    (
                        piece_dir,
                        f"folder name does not match regex `{self.part_config.piece_folder_regex}`",
                    )
                )
                continue

            # Extract serial from folder name
            match = self._sn_full_regex.search(piece_dir.name)
            serial = match.group("sn") if match else None

            if not serial:
                result.rejected['all'].append(
                    (piece_dir, "could not extract serial number using regex")
                )
                continue

            serial = serial.split("-")[0]
            fs_pieces[serial].append(piece_dir)

        for charac in self.metric_characs:
            processed_sn = self._get_processed_serials(charac)
            to_process = tracking_sn - processed_sn
            print(f"Tracking SN: {len(tracking_sn)}, Processed SN for {charac}: {len(processed_sn)}, To process: {len(to_process)}")

            self.logger.info(
                "[%s] %s to process (tracking=%s, done=%s)",
                charac,
                len(to_process),
                len(tracking_sn),
                len(processed_sn),
            )

            for sn in to_process:
                if sn in fs_pieces:
                    result.discovered[charac].extend(fs_pieces[sn])
            
            self.logger.info(
                "Piece discovery completed for metric %s : %s accepted / %s rejected",
                charac,
                len(result.discovered[charac]),
                len(result.rejected['all']),
            )

        for piece, reason in result.rejected['all']:
            self.logger.warning("Rejected piece folder %s: %s", piece.name, reason)

        return result
