from pathlib import Path
from src.mle_heatmap_wrapper.cli.main import HeatmapWrapper
from src.mle_heatmap_wrapper.core.config import config
from src.mle_heatmap_wrapper.core.logger import LoggerManager, get_logger
from src.mle_heatmap_wrapper.core.metrics import metrics_collector
from src.mle_heatmap_wrapper.core.piece_discovery import PieceDiscovery
from src.mle_heatmap_wrapper.core.suppliers_config import get_suppliers_config
from src.mle_heatmap_wrapper.models.part_config import PartConfigManager
from src.mle_heatmap_wrapper.models.data_models import PartConfiguration
from src.mle_heatmap_wrapper.parsers.registry import get_parser_class
from src.mle_heatmap_wrapper.validators.data_validator import validate_input_data
from src.mle_heatmap_wrapper.processors.geometry_processor import GeometryProcessor
from src.mle_heatmap_wrapper.exporters.csv_exporter import CSVExporter, MetricsExporter
from src.mle_heatmap_wrapper.exporters.mongo_exporter import MongoExporter

wrapper = HeatmapWrapper()

input_path = Path('./data/in/mlx')
part_number = "362-850-019"
supplier = "mlx"
operation = "OP650"
metrics = ["thickness"] #, "tangent", "chords"]
output= Path('./data/out/mlx')


LoggerManager.setup_logging()
logger = get_logger(__name__)
config_manager = PartConfigManager()
metrics_exporter = MetricsExporter()

def _get_parser( supplier: str, part_config: PartConfiguration):
    """Get parser for supplier: from part_config, suppliers_config, or default."""
    # 1. part_config.supplier_settings can override parser per part+supplier
    parser_name = part_config.supplier_settings.get("parser_class")
    # 2. fallback to suppliers_config
    if not parser_name:
        parser_name = get_suppliers_config().get_parser_class_name(supplier)
    # 3. default mapping for backward compatibility
    if not parser_name:
        parser_name = _default_parser_for_supplier(supplier)
    parser_class = get_parser_class(parser_name)
    return parser_class(part_config)

def _default_parser_for_supplier( supplier: str) -> str:
    """Fallback when no parser in config."""
    key = supplier.upper().replace("_", " ")
    mapping = {"CZT": "CZTParser", "MLX": "MLXParser", "TECT PA": "TECTParser"}
    if key in mapping:
        return mapping[key]
    raise ValueError(f"Unknown supplier: {supplier}. Add to suppliers_config.yaml.")

def _list_available_configurations():
    """List all available part-supplier configurations."""
    logger.info("\nAvailable configurations:")
    combinations = config_manager.list_supported_combinations()

    for part_num, supp, sections in combinations:
        logger.info(f"  - {part_num} / {supp} ({sections} sections)")


## ----------------------------------------------

input_dir=input_path
part_number=part_number
supplier=supplier
metrics=metrics
operation=operation
output_dir=Path(output) if output else None

logger.info("=" * 70)
logger.info("MLE HEATMAP WRAPPER - BATCH EXECUTION START")
logger.info("=" * 70)

supplier_normalized = get_suppliers_config().resolve_supplier(supplier)

part_config = config_manager.get_configuration(
    part_number, supplier_normalized, operation=operation
)

if not part_config:
    logger.error(
        "No configuration found for %s - %s", part_number, supplier
    )
    _list_available_configurations()
    print(False)

if not input_dir.exists():
    logger.error("Input directory not found: %s", input_dir)
    print(False)

output_dir = output_dir or config.paths.output_dir
output_dir.mkdir(parents=True, exist_ok=True)

parser = _get_parser(supplier_normalized, part_config)

discovery = PieceDiscovery(part_config, metrics).discover(input_dir)

for metric in metrics:
    logger.info(
        "Discovered %s pieces for metric '%s'", len(discovery.discovered[metric]), metric
    )
if not discovery.discovered:
    logger.error("No valid piece folders discovered in: %s", input_dir)
    print(False)

execution_metrics = metrics_collector.start_execution(
    part_number=part_number,
    supplier=supplier,
    sections_expected=part_config.sections_count,
)
for metric in metrics:
    execution_metrics.add_custom_metric(
        f"pieces_discovered_{metric}", float(len(discovery.discovered[metric]))
)
execution_metrics.add_custom_metric(
    "pieces_rejected", float(len(discovery.rejected['all']))
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
    logger.info("Processing piece folder: %s", piece_dir.name)
    try:
        input_data = parser.parse_piece_folder(piece_dir)
        execution_metrics.input_points_count += input_data.points_count

        input_data.nominal_sections = parser.parse_nominal(Path(part_config.nominal.get("section_file_path")))
        input_data.nominal_skeleton = parser.parse_nominal(Path(part_config.nominal.get("skeleton_file_path")))
        input_data.nominal_heatmap_widthness = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_widthness_file_path")))
        input_data.nominal_heatmap_thickness_intrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_intrados_file_path")))
        input_data.nominal_heatmap_thickness_extrados = parser.parse_nominal_heatmap(Path(part_config.nominal.get("heatmap_thickness_extrados_file_path")))

        validation_result = validate_input_data(input_data)
        execution_metrics.sections_processed += (validation_result.sections_validated)

        for warning in validation_result.warnings:
            execution_metrics.add_warning()

        if not validation_result.is_valid:
            failed_count += 1
            execution_metrics.sections_failed += 1
            for error in validation_result.errors:
                execution_metrics.add_error(f"{piece_dir.name}: {error}")
            continue
        
        results = processor.process_all_metrics(input_data, metrics, start_radius=4, delta_radius=1, neigh_points=2)

        mongo_out = db_export.export_batch(results=results)
        
        # piece_output = exporter.export_piece_results(results=results, piece_metadata=input_data.piece_metadata)

        # exported_files.append(piece_output)

        success_count += 1
    except Exception as exc:
        failed_count += 1
        execution_metrics.add_error(f"{piece_dir.name}: {exc}")
        logger.error(
            "Piece processing failed for %s: %s",
            piece_dir,
            exc,
            exc_info=True,
        )

execution_metrics.add_custom_metric("pieces_success", float(success_count))
execution_metrics.add_custom_metric("pieces_failed", float(failed_count))
execution_metrics = metrics_collector.finalize_execution()

metrics_exporter.export_metrics(execution_metrics)
metrics_exporter.export_summary(execution_metrics)

logger.info("=" * 70)
logger.info(
    "BATCH EXECUTION FINISHED - success: %s / failed: %s",
    success_count,
    failed_count,
)
# logger.info("Exported %s files:", len(exported_files))
# for file_path in exported_files:
#     logger.info(f"  - {file_path.name}")
# logger.info("=" * 70)

# print(success_count > 0)

