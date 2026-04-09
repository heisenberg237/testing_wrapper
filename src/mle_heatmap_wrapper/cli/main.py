"""
Command-line interface for MLE Heatmap Wrapper.
Main entry point for executing heatmap generation.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from ..core.config import config
from ..core.logger import LoggerManager, get_logger
from ..core.metrics import metrics_collector
from ..core.piece_discovery import PieceDiscovery
from ..core.suppliers_config import get_suppliers_config
from ..models.part_config import PartConfigManager
from ..models.data_models import MetricType, PartConfiguration
from ..parsers.registry import get_parser_class
from ..validators.data_validator import validate_input_data
from ..processors.geometry_processor import GeometryProcessor
from ..exporters.csv_exporter import CSVExporter, MetricsExporter
from src.mle_heatmap_wrapper.exporters.mongo_exporter import MongoExporter


class HeatmapWrapper:
    """Main wrapper orchestrating batch and legacy pipelines."""

    def __init__(self):
        LoggerManager.setup_logging()
        self.logger = get_logger(self.__class__.__name__)
        self.config_manager = PartConfigManager()
        self.metrics_exporter = MetricsExporter()

    def run_batch(
        self,
        input_dir: Path,
        part_number: str,
        supplier: str,
        operation: str="OP420",
        metrics: Optional[list] = None,
        output_dir: Optional[Path] = None,
    ) -> bool:
        """
        Execute folder-based pipeline:
        supplier + partnumber + metrics + input root + output root.
        """
        self.logger.info("=" * 70)
        self.logger.info("MLE HEATMAP WRAPPER - BATCH EXECUTION START")
        self.logger.info("=" * 70)

        try:
            supplier_normalized = get_suppliers_config().resolve_supplier(supplier)
            part_config = self.config_manager.get_configuration(
                part_number, supplier_normalized, operation
            )
            if not part_config:
                self.logger.error(
                    "No configuration found for %s - %s - %s", part_number, supplier, operation
                )
                self._list_available_configurations()
                return False

            if not input_dir.exists():
                self.logger.error("Input directory not found: %s", input_dir)
                return False

            output_dir = output_dir or config.paths.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            parser = self._get_parser(supplier_normalized, part_config)
            discovery = PieceDiscovery(part_config, metrics).discover(input_dir)
            
            pieces_ = []
            for charac in metrics:
                pieces_.extend(discovery.discovered.get(charac, []))
                self.logger.info(
                    "Discovered %s pieces for metric '%s'",
                    len(discovery.discovered.get(charac, [])),
                    charac,
                )

            if not pieces_:
                self.logger.error("No valid piece folders discovered in: %s", input_dir)
                return False

            execution_metrics = metrics_collector.start_execution(
                part_number=part_number,
                supplier=supplier,
                sections_expected=part_config.sections_count,
            )
            for charac in metrics:   
                execution_metrics.add_custom_metric(
                    f"pieces_discovered_{charac}", float(len(discovery.discovered.get(charac, [])))
                )
            execution_metrics.add_custom_metric(
                "pieces_rejected", float(len(discovery.rejected.get('all', [])))
            )

            processor = GeometryProcessor()
            exporter = CSVExporter(output_dir=output_dir)
            db_export = MongoExporter()

            success_count = 0
            failed_count = 0
            exported_files = []

            # combine all the discovered pieces in each characs
            union_pieces = set()
            for charac in discovery.discovered.keys():
                union_pieces.update(set(discovery.discovered[charac]))

            for piece_dir in union_pieces:
                self.logger.info("Processing piece folder: %s", piece_dir.name)
                try:
                    input_data = parser.parse_piece_folder(piece_dir)
                    execution_metrics.input_points_count += input_data.points_count

                    input_data.nominal_sections = parser.parse_nominal(part_config.nominal.get("section_file_path"))
                    input_data.nominal_skeleton = parser.parse_nominal(part_config.nominal.get("skeleton_file_path"))
                    input_data.nominal_heatmap_widthness = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_widthness_file_path")))
                    input_data.nominal_heatmap_thickness_intrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_intrados_file_path")))
                    input_data.nominal_heatmap_thickness_extrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_extrados_file_path")))

                    validation_result = validate_input_data(input_data)
                    execution_metrics.sections_processed += (
                        validation_result.sections_validated
                    )

                    for warning in validation_result.warnings:
                        execution_metrics.add_warning()

                    if not validation_result.is_valid:
                        failed_count += 1
                        execution_metrics.sections_failed += 1
                        for error in validation_result.errors:
                            execution_metrics.add_error(f"{piece_dir.name}: {error}")
                        continue

                    results = processor.process_all_metrics(
                        input_data, 
                        metrics, 
                        start_radius=2, 
                        delta_radius=1, 
                        neigh_points=2
                    )

                    mongo_out = db_export.export_batch(results=results)
                    
                    piece_output = exporter.export_piece_results(
                        results=results,
                        piece_metadata=input_data.piece_metadata,
                    )

                    exported_files.append(piece_output)
                    
                    success_count += 1

                except Exception as exc:
                    failed_count += 1
                    execution_metrics.add_error(f"{piece_dir.name}: {exc}")
                    self.logger.error(
                        "Piece processing failed for %s: %s",
                        piece_dir,
                        exc,
                        exc_info=True,
                    )

            execution_metrics.add_custom_metric("pieces_success", float(success_count))
            execution_metrics.add_custom_metric("pieces_failed", float(failed_count))
            execution_metrics = metrics_collector.finalize_execution()

            self.metrics_exporter.export_metrics(execution_metrics)
            self.metrics_exporter.export_summary(execution_metrics)

            self.logger.info("=" * 70)
            self.logger.info(
                "BATCH EXECUTION FINISHED - success: %s / failed: %s",
                success_count,
                failed_count,
            )
            self.logger.info("Exported %s files:", len(exported_files))
            for file_path in exported_files:
                self.logger.info(f"  - {file_path.name}")
            self.logger.info("=" * 70)

            return success_count > 0

        except Exception as exc:
            self.logger.error("Batch execution failed: %s", exc, exc_info=True)
            try:
                current_metrics = metrics_collector.get_current_metrics()
                if current_metrics:
                    current_metrics.add_error(str(exc))
                    metrics_collector.finalize_execution()
            except Exception:
                pass
            return False

    def run_single_file(
        self,
        piece_folder: Path,
        part_number: str,
        supplier: str,
        operation: str="OP420",
        metrics: Optional[list] = None,
        output_dir: Optional[Path] = None,
    ) -> bool:
        """Legacy mode: process one already normalized CSV file."""

        self.logger.info("Running in legacy single-file mode")
        supplier_normalized = get_suppliers_config().resolve_supplier(supplier)
        part_config = self.config_manager.get_configuration(
            part_number, supplier_normalized, operation
        )
        if not part_config:
            self.logger.error(
                "No configuration found for %s - %s", part_number, supplier
            )
            return False

        output_dir = output_dir or config.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        parser = self._get_parser(supplier_normalized, part_config)
        input_data = parser.parse_piece_folder(piece_folder)
          
        input_data.nominal_sections = parser.parse_nominal(Path(part_config.nominal.get("section_file_path")))
        input_data.nominal_skeleton = parser.parse_nominal(Path(part_config.nominal.get("skeleton_file_path")))
        input_data.nominal_heatmap_widthness = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_widthness_file_path")))
        input_data.nominal_heatmap_thickness_intrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_intrados_file_path")))
        input_data.nominal_heatmap_thickness_extrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_extrados_file_path")))

        self.input_data_ =  input_data
        validation_result = validate_input_data(input_data)
        if not validation_result.is_valid:
            for error in validation_result.errors:
                self.logger.error(error)
            return False

        processor = GeometryProcessor()
        results = processor.process_all_metrics(input_data, metrics)
        exporter = CSVExporter(output_dir=output_dir)
        exported = exporter.export_batch(results)

        self.results_ = results

        self.logger.info("Legacy mode exported %s files", len(exported))
        
        return True

    def _get_parser(self, supplier: str, part_config: PartConfiguration):
        """Get parser for supplier: from part_config, suppliers_config, or default."""
        # 1. part_config.supplier_settings can override parser per part+supplier
        parser_name = part_config.supplier_settings.get("parser_class")
        # 2. fallback to suppliers_config
        if not parser_name:
            parser_name = get_suppliers_config().get_parser_class_name(supplier)
        # 3. default mapping for backward compatibility
        if not parser_name:
            parser_name = self._default_parser_for_supplier(supplier)
        parser_class = get_parser_class(parser_name)
        return parser_class(part_config)

    def _default_parser_for_supplier(self, supplier: str) -> str:
        """Fallback when no parser in config."""
        key = supplier.upper().replace("_", " ")
        mapping = {"CZT": "CZTParser", "MLX": "MLXParser", "TECT PA": "TECTParser"}
        if key in mapping:
            return mapping[key]
        raise ValueError(f"Unknown supplier: {supplier}. Add to suppliers_config.yaml.")

    def _list_available_configurations(self):
        """List all available part-supplier configurations."""
        self.logger.info("\nAvailable configurations:")
        combinations = self.config_manager.list_supported_combinations()

        for part_num, supp, sections in combinations:
            self.logger.info(f"  - {part_num} / {supp} ({sections} sections)")


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Wrapper MLE Heatmap - traitement dossiers pièces + GEOM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mode batch (recommandé)
  %(prog)s --input-dir data/in/mlx --part-number 362 --supplier MLX --output output --metrics widthness tangent

  # Mode legacy fichier unique
  %(prog)s --input-file data/input.csv --part-number 362 --supplier CZT --output output
        """,
    )

    parser.add_argument(
        "-p",
        "--part-number",
        type=str,
        help="Part number (e.g., 362, 364)",
    )
    parser.add_argument(
        "-s",
        "--supplier",
        type=str,
        help='Supplier name (CZT, MLX, "TECT PA")',
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Input root directory containing piece folders",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Legacy mode: input file (CSV)",
    )

    parser.add_argument(
        "-m",
        "--metrics",
        nargs="+",
        choices=[m.value for m in MetricType],
        help="Metrics to compute (default: all)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List available part-supplier configurations",
    )

    args = parser.parse_args()

    if args.list_configs:
        wrapper = HeatmapWrapper()
        wrapper._list_available_configurations()
        return 0

    if not args.part_number or not args.supplier:
        print("Error: --part-number and --supplier are required", file=sys.stderr)
        return 1

    if args.nominal and not args.nominal.exists():
        print(f"Error: Nominal file not found: {args.nominal}", file=sys.stderr)
        return 1

    wrapper = HeatmapWrapper()

    if args.input_dir:
        input_path = Path(args.input_dir) if not isinstance(args.input_dir, Path) else args.input_dir
        success = wrapper.run_batch(
            input_dir=input_path,
            part_number=args.part_number,
            supplier=args.supplier,
            nominal_file=args.nominal,
            metrics=args.metrics,
            output_dir=Path(args.output) if args.output else None,
        )
    elif args.input_file:
        if not args.input_file.exists():
            print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
            return 1
        success = wrapper.run_single_file(
            input_file=args.input_file,
            part_number=args.part_number,
            supplier=args.supplier,
            nominal_file=args.nominal,
            metrics=args.metrics,
            output_dir=args.output,
        )
    else:
        print(
            "Error: provide either --input-dir (batch) or --input-file (legacy)",
            file=sys.stderr,
        )
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
