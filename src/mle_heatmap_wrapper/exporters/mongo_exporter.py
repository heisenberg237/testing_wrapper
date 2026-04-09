"""
Mongo exporter for MLE heatmap results.

This exporter converts ProcessingResult objects into the legacy MongoDB
document structure used by the historical ETL and inserts them into
the appropriate collection.

Features
--------
- Compatible with BaseExporter
- Legacy radius/section normalization (R5 -> 05, CR03 -> 03)
- Thickness metric multi-side support (intrados / extrados / both)
- Robust dataframe validation
- Automatic collection resolution
- Mongo bulk-safe insertion
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import pandas as pd
from pymongo import MongoClient

from .base_exporter import BaseExporter
from ..models.data_models import ProcessingResult
from ..core.logger import get_logger
from ..core.config import COLLECTION_MAPPING, SIDE_MAPPING


class MongoExporter(BaseExporter):
    """
    Export ProcessingResult objects to MongoDB using legacy schema.

    Parameters
    ----------
    mongo_url : str | None
        MongoDB connection string. If None, environment variable
        MONGO_URL_MLE_HEATMAP is used.
    database : str
        Target database name (default: mleHeatmap)
    """
    DEFAULT_DATABASE = "mleHeatmap"

    COLLECTION_MAPPING = COLLECTION_MAPPING 

    SIDE_MAPPING = SIDE_MAPPING

    def __init__(
            self, 
            mongo_url: str | None = None,
            database: str = DEFAULT_DATABASE
        ):

        super().__init__(output_dir=Path(".")) 

        self.logger = get_logger(self.__class__.__name__)

        self.mongo_url = mongo_url or os.getenv("MONGO_URI")

        if not self.mongo_url:
            raise RuntimeError("Missing env MONGO_URI")

        self.client = MongoClient(self.mongo_url)
        self.db = self.client[database]

    # -----------------------------
    # Public API
    # -----------------------------
    def export(self, result: ProcessingResult) -> Path:
        """
        Export one ProcessingResult into MongoDB
        """

        if not result.success:
            raise ValueError("Cannot export unsuccessful result")
        
        if result.data is None or result.data.empty:
            raise ValueError("ProcessingResult contains empty dataframe")

        df = self._prepare_dataframe(result.data)

        collection = self._resolve_collection(result.metric_type)

        document = self._build_document(result, df)

        action = self._upsert_document(collection, document)

        self.logger.info(
            "Mongo %s metric=%s rows=%d",
            action,
            result.metric_type,
            len(df),
        )

        # Mongo exporter does not create file, return dummy path
        return Path(f"mongodb://{action}")

    # ------------------------------------------------------------------
    # Data preparation
    # ------------------------------------------------------------------
    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize dataframe to legacy format.
        """

        required = {"radius", "section", "value"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        data = df.copy()

        # normalize radius & section like legacy ETL
        data["radius"] = data["radius"].apply(self._normalize_label)
        data["section"] = data["section"].apply(self._normalize_label)

        return data


    # ------------------------------------------------------------------
    # Mongo document builder
    # ------------------------------------------------------------------
    def _build_document(
        self,
        result: ProcessingResult,
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Build MongoDB document following legacy ETL schema.
        """

        piece = result.piece_metadata

        base = {
            "date": getattr(piece, "datetimestamp", None),
            "supplier": result.part_config.supplier,
            "partNumber": result.part_config.part_number,
            "operation": result.part_config.operation,
            "serial": getattr(piece, "serial_number_short", None),
        }

        sides = self._detect_sides(result, df)

        for side in sides:
            side_df = df if side == "both" else df[df["side"] == side]

            if side_df.empty:
                continue

            pivot = self._pivot_dataframe(side_df)

            base[self.SIDE_MAPPING[side]] = self._build_side_block(pivot)

        return base

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_collection(self, metric_type: str):
        """
        Resolve Mongo collection from metric type.
        """

        metric = metric_type.lower()
        collection_name = self.COLLECTION_MAPPING.get(metric, metric)

        return self.db[collection_name]
    
    def _detect_sides(
        self,
        result: ProcessingResult,
        df: pd.DataFrame,
    ) -> List[str]:
        """
        Determine sides to export.
        """

        metric = result.metric_type.lower()

        if "thickness" not in metric:
            return ["both"]

        if "side" not in df.columns:
            return ["both"]

        sides = sorted(df["side"].dropna().unique())

        if not sides:
            return ["both"]

        return sides
    
    def _pivot_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pivot dataframe into matrix form.
        """

        pivot = df.pivot(
            index="radius",
            columns="section",
            values="value",
        )

        pivot = pivot.sort_index(key=lambda x: x.astype(int))
        pivot = pivot.sort_index(axis=1, key=lambda x: x.astype(int))

        return pivot
    
    def _build_side_block(self, pivot: pd.DataFrame) -> Dict[str, Any]:
        """
        Build one side block for Mongo document.
        """

        matrix = pivot.to_numpy().tolist()
        radius = pivot.index.tolist()
        sections = pivot.columns.tolist()

        radius_view = pivot.to_dict(orient="index")
        sections_view = pivot.to_dict()

        wing_end = [
            pivot[col].dropna().iloc[-1]
            for col in pivot.columns
            if not pivot[col].dropna().empty
        ]

        return {
            "file": "generated",
            "matrix": matrix,
            "radius": radius,
            "sections": sections,
            "radiusView": radius_view,
            "sectionsView": sections_view,
            "wingEnd": wing_end,
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_label(value: Any) -> str:
        """
        Extract numeric part and zero-pad (legacy ETL compatible).

        Examples
        --------
        R5   -> 05
        CR3  -> 03
        CR03 -> 03
        """

        match = re.search(r"\d+", str(value))
        if not match:
            return str(value)

        val = match.group()
        return val if len(val) > 1 else f"0{val}"
    
    def _upsert_document(self, collection, document):
        """
        Insert or update document based on timestamp freshness.
        """

        filter_query = {
            "serial": document["serial"],
            "supplier": document["supplier"],
            "operation": document["operation"],
            "partNumber": document["partNumber"],
        }

        existing = collection.find_one(filter_query, {"date": 1})

        # No existing document → insert
        if not existing:
            collection.insert_one(document)
            return "inserted"

        existing_date = existing.get("date")
        new_date = document.get("date")

        # if no date info, replace defensively
        if not existing_date or not new_date:
            collection.replace_one(filter_query, document, upsert=True)
            return "replaced"

        # update only if newer
        if new_date > existing_date:
            collection.replace_one(filter_query, document, upsert=True)
            return "updated"

        return "skipped"