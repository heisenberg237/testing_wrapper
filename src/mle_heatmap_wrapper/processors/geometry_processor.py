"""Geometry processor for metric calculations."""

import time
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from src.mle_heatmap_wrapper.core.config import config
from src.mle_heatmap_wrapper.core.logger import get_logger
from src.mle_heatmap_wrapper.core.metrics import metrics_collector
from src.mle_heatmap_wrapper.models.data_models import InputData, MetricType, ProcessingResult

from mle_heatmap_generator.BuilderHeatmap import BuilderHeatmap
from mle_heatmap_generator.builder_section.cavity.CavityPreprocessor import CavityPreprocessor
from mle_heatmap_generator.builder_section.wings.ThicknessPreprocessor import ThicknessPreprocessor
from mle_heatmap_generator.builder_section.cavity.ChordSectionBuilder import ChordSectionBuilder
from mle_heatmap_generator.builder_section.cavity.TangentSectionBuilder import TangentSectionBuilder
from mle_heatmap_generator.builder_section.cavity.WidthSectionBuilder import WidthSectionBuilder
from mle_heatmap_generator.builder_section.wings.ThicknessSuctionSideSectionBuilder import ThicknessSuctionSideSectionBuilder
from mle_heatmap_generator.builder_section.wings.ThicknessPressureSideSectionBuilder import ThicknessPressureSideSectionBuilder
from mle_heatmap_generator.builder_section.nominal_funcs import compute_nominal_reference_skeleton_points, compute_nominal_chord_tangent_reference_system_on_sections

logger = get_logger(__name__)

class GeometryProcessor:
    """Compute geometric metrics from normalized point cloud DataFrames."""

    def __init__(self, enable_op_data: Optional[bool] = None):
        self.enable_op_data = (
            enable_op_data
            if enable_op_data is not None
            else config.processing.enable_op_data
        )
        self.logger = get_logger(self.__class__.__name__)
        self._calculation_package = self._import_calculation_package()
        self.heatmap_cavity_builder: BuilderHeatmap = None
        self.heatmap_wings_builder: BuilderHeatmap = None
        self.nominal_refs_on_sections: pd.DataFrame = None
        self.nominal_skels_intersect_points: pd.DataFrame = None

    def _import_calculation_package(self):
        try:
            import mle_heatmap_generator as package

            self.logger.info("External package mle_heatmap_generator detected")
            return package
        except ImportError:
            self.logger.info(
                "External package not installed, please install it first `pip install safranae-mle-heatmapgenerator`"
            )
            raise

    def process_all_metrics(
        self,
        input_data: InputData,
        metrics: Optional[List[str]] = None,
        start_radius=4, 
        delta_radius=1,
        neigh_points=2,
    ) -> List[ProcessingResult]:
        if metrics is None:
            metrics = [
                MetricType.WIDTHNESS.value,
                MetricType.TANGENT.value,
                MetricType.CHORDS.value,
                MetricType.THICKNESS.value,
            ]

        if set(metrics).intersection([MetricType.WIDTHNESS.value, MetricType.TANGENT.value, MetricType.CHORDS.value]):
            cavities_processor = CavityPreprocessor(start_radius=start_radius, delta_radius=delta_radius)
            self.heatmap_cavity_builder = BuilderHeatmap(df_sections=input_data.dataframe, preprocessor=cavities_processor)
        
        if set(metrics).intersection([MetricType.TANGENT.value, MetricType.CHORDS.value]):

            self.nominal_skels_intersect_points = compute_nominal_reference_skeleton_points(nominal_skeletons=input_data.nominal_skeleton, start_radius=start_radius, delta_radius=delta_radius)
            self.nominal_refs_on_sections = compute_nominal_chord_tangent_reference_system_on_sections(skeletons=input_data.nominal_sections, sections=input_data.dataframe)

        if set(metrics).intersection([MetricType.THICKNESS.value]):
            wings_processor = ThicknessPreprocessor(start_radius=start_radius, delta_radius=delta_radius, neigh_points=neigh_points)
            self.heatmap_wings_builder = BuilderHeatmap(df_sections=input_data.dataframe, preprocessor=wings_processor)

        current_metrics = metrics_collector.get_current_metrics()
        results: List[ProcessingResult] = []

        for metric in metrics:
            try:
                result = self._process_metric(metric, input_data)
                results.append(result)
                if current_metrics:
                    current_metrics.metrics_generated.append(metric)
                    current_metrics.output_rows_count += result.rows_count
            except Exception as exc:
                self.logger.error(
                    "Failed to compute %s: %s", metric, exc, exc_info=True
                )
                results.append(
                    ProcessingResult(
                        metric_type=metric,
                        data=pd.DataFrame(),
                        part_config=input_data.part_config,
                        piece_metadata=input_data.piece_metadata,
                        success=False,
                        error_message=str(exc),
                    )
                )
                if current_metrics:
                    current_metrics.add_error(f"Failed to compute {metric}: {exc}")
        return results

    def _process_metric(self, metric: str, input_data: InputData) -> ProcessingResult:
        start_time = time.time()
        dispatch: Dict[str, Callable[[InputData], pd.DataFrame]] = {
            MetricType.WIDTHNESS.value: self._compute_widthness,
            MetricType.TANGENT.value: self._compute_tangent,
            MetricType.CHORDS.value: self._compute_chords,
            MetricType.THICKNESS.value: self._compute_thickness
        }

        if metric not in dispatch:
            raise ValueError(f"Unknown metric type: {metric}")

        result_df = dispatch[metric](input_data)
        processing_time = time.time() - start_time
        return ProcessingResult(
            metric_type=metric,
            data=result_df,
            part_config=input_data.part_config,
            piece_metadata=input_data.piece_metadata,
            success=True,
            processing_time_seconds=processing_time,
        )

    def _compute_widthness(self, input_data: InputData) -> pd.DataFrame:
        heatmap_width = self.heatmap_cavity_builder.build(section_builder=WidthSectionBuilder, 
                                                            nominal_scalar_heatmap=input_data.nominal_heatmap_widthness)
        df = self._normalize_output(heatmap_width)
        df["side"] = "both"

        return df
        
    def _compute_tangent(self, input_data: InputData) -> pd.DataFrame:
        heatmap_tangent = self.heatmap_cavity_builder.build(section_builder=TangentSectionBuilder, 
                                                            nominal_skeletons=self.nominal_skels_intersect_points, 
                                                            nominal_refs=self.nominal_refs_on_sections)
        

        df = self._normalize_output(heatmap_tangent)
        df["side"] = "both"

        return df

    def _compute_chords(self, input_data: InputData) -> pd.DataFrame:
        heatmap_chord = self.heatmap_cavity_builder.build(section_builder=ChordSectionBuilder, 
                                                          nominal_skeletons=self.nominal_skels_intersect_points, 
                                                          nominal_refs=self.nominal_refs_on_sections)
        
        df = self._normalize_output(heatmap_chord)
        df["side"] = "both"

        return df
    
    def _compute_thickness(self, input_data: InputData) -> pd.DataFrame:
        heatmap_thickness_extrados = self._compute_thickness_extrados(input_data)
        heatmap_thickness_intrados = self._compute_thickness_intrados(input_data)
        df = pd.concat([heatmap_thickness_intrados, heatmap_thickness_extrados], ignore_index=True)
        return df

    def _compute_thickness_extrados(self, input_data: InputData) -> pd.DataFrame:
        heatmap_thickness_extrados = self.heatmap_wings_builder.build(section_builder=ThicknessSuctionSideSectionBuilder, 
                                                                       nominal_scalar_heatmap=input_data.nominal_heatmap_thickness_extrados)
        
        df = self._normalize_output(heatmap_thickness_extrados)
        df["side"] = "ext"

        return df

    def _compute_thickness_intrados(self, input_data: InputData) -> pd.DataFrame:
        heatmap_thickness_intrados = self.heatmap_wings_builder.build(section_builder=ThicknessPressureSideSectionBuilder, 
                                                                       nominal_scalar_heatmap=input_data.nominal_heatmap_thickness_intrados)
        
        df = self._normalize_output(heatmap_thickness_intrados)
        df["side"] = "int"

        return df

    def _normalize_output(self, result) -> pd.DataFrame:
        if hasattr(result, "__dataclass_fields__"):
            import dataclasses

            result = dataclasses.asdict(result)
        if isinstance(result, dict):
            return pd.DataFrame([result])
        if isinstance(result, pd.DataFrame):
            return result
        raise TypeError(f"Unexpected result type: {type(result)}")
