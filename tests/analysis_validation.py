"""
HeatmapValidator — Étude comparative REF vs TOVALID
====================================================
Quantifie l'impact d'une évolution de calcul sur les résultats heatmap.

Améliorations v2 :
  - Corrections de bugs (variables non définies dans plot_diff_heatmap)
  - Sauvegarde PNG + HTML de toutes les figures
  - Rapport HTML de synthèse auto-généré
  - Logging structuré + barre de progression (tqdm)
  - Chargement parallèle des CSV (ThreadPoolExecutor)
  - Nouvelles analyses :
      * Ranking des pires SN par métrique
      * Corrélation d'erreur inter-métriques
      * Distribution des erreurs (violin + box)
      * Scatter REF vs TOVALID par point physique
      * Résumé statistique global (pass rate, percentiles)
  - Figures Plotly retravaillées : palette cohérente, annotations, titres explicites
"""

import re
import logging
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from tqdm import tqdm

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("HeatmapValidator")

# ---------------------------------------------------------------------------
# PALETTE & THEME
# ---------------------------------------------------------------------------
PALETTE = {
    "primary":   "#2563EB",   # bleu
    "secondary": "#10B981",   # vert
    "danger":    "#EF4444",   # rouge
    "warning":   "#F59E0B",   # orange
    "neutral":   "#6B7280",   # gris
    "bg":        "#F8FAFC",
    "surface":   "#FFFFFF",
    "text":      "#1E293B",
}

PLOTLY_TEMPLATE = dict(
    layout=dict(
        font=dict(family="IBM Plex Sans, Arial, sans-serif", color=PALETTE["text"]),
        paper_bgcolor=PALETTE["bg"],
        plot_bgcolor=PALETTE["surface"],
        title=dict(font=dict(size=16, color=PALETTE["text"]), x=0.5, xanchor="center"),
        colorway=[
            PALETTE["primary"], PALETTE["secondary"], PALETTE["danger"],
            PALETTE["warning"], PALETTE["neutral"], "#8B5CF6", "#EC4899",
        ],
        margin=dict(t=70, b=60, l=70, r=40),
        hoverlabel=dict(bgcolor=PALETTE["surface"], font_size=12),
    )
)


def _apply_theme(fig, title: str = "", xaxis_title: str = "", yaxis_title: str = ""):
    """Applique le thème commun + métadonnées à une figure Plotly."""
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        title_text=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
    )
    fig.update_xaxes(showgrid=True, gridcolor="#E2E8F0", linecolor="#CBD5E1")
    fig.update_yaxes(showgrid=True, gridcolor="#E2E8F0", linecolor="#CBD5E1")
    return fig


# ===========================================================================
# CLASSE PRINCIPALE
# ===========================================================================
class HeatmapValidator:
    """
    Validation REF vs TOVALID basée sur alignement physique (R, CR).

    Paramètres
    ----------
    ref_path     : chemin racine des fichiers de référence
    tovalid_path : chemin racine des fichiers à valider
    tol          : seuil de tolérance absolue (défaut 1e-2)
    output_dir   : dossier de sortie pour les figures et le rapport
    n_workers    : nombre de threads pour le chargement parallèle
    """

    SN_REGEX = re.compile(r"[A-Za-z]{2}\d{6}-[A-Za-z0-9]")
    METRICS   = ["chord", "widthness", "tangent"]

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------
    def __init__(
        self,
        ref_path: str,
        tovalid_path: str,
        tol: float = 1e-2,
        output_dir: str = "plots",
        n_workers: int = 8,
    ):
        self.ref_path      = Path(ref_path)
        self.tovalid_path  = Path(tovalid_path)
        self.tol           = tol
        self.n_workers     = n_workers
        self.output_dir    = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ref_index:    dict = {}
        self.tovalid_index: dict = {}
        self.results:      pd.DataFrame | None = None
        self.dataset_stats: pd.DataFrame | None = None
        self._aligned_cache: dict = {}
        self._figures: list[dict] = []   # {"name": str, "fig": Figure}

        log.info("HeatmapValidator initialisé — tol=%.2e | output=%s", tol, self.output_dir)

    # ------------------------------------------------------------------
    # EXTRACTION DE MÉTADONNÉES
    # ------------------------------------------------------------------
    def _extract_info(self, path: Path):
        name   = path.name.lower()
        parent = path.parent.name.lower()

        sn_match = self.SN_REGEX.search(name)
        sn       = sn_match.group() if sn_match else None
        metric   = next((m for m in self.METRICS if m in name), None)

        try:
            plant, pn, *_ = parent.split("_")
        except ValueError:
            plant, pn = None, None

        operation = "OP650" if plant == "mlx" else "OP420"
        return sn, metric, plant, pn, operation

    # ------------------------------------------------------------------
    # INDEXATION
    # ------------------------------------------------------------------
    def _index_files(self, root: Path) -> dict:
        index = {}
        for p in root.rglob("*.csv"):
            sn, metric, plant, pn, operation = self._extract_info(p)
            if sn and metric:
                index[(sn, metric)] = {
                    "path": p, "plant": plant, "pn": pn, "operation": operation,
                }
        return index

    def build_index(self):
        log.info("Indexation REF  → %s", self.ref_path)
        self.ref_index     = self._index_files(self.ref_path)
        log.info("  %d fichiers trouvés", len(self.ref_index))

        log.info("Indexation TOVALID → %s", self.tovalid_path)
        self.tovalid_index = self._index_files(self.tovalid_path)
        log.info("  %d fichiers trouvés", len(self.tovalid_index))

    # ------------------------------------------------------------------
    # CHARGEMENT & STANDARDISATION
    # ------------------------------------------------------------------
    def _load_and_standardize(self, path: Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        df = df.rename(columns={df.columns[0]: "R"}).dropna(how="all")

        df["R"] = (
            df["R"].astype(str)
            .str.extract(r"(\d+\.?\d*)")[0]
            .astype(float)
        )

        new_cols = []
        for col in df.columns:
            if col == "R":
                new_cols.append(col)
            else:
                val = re.search(r"(\d+\.?\d*)", str(col))
                new_cols.append(float(val.group()) if val else np.nan)
        df.columns = new_cols

        return df

    def _to_long(self, df: pd.DataFrame) -> pd.DataFrame:
        df_long = df.melt(id_vars="R", var_name="CR", value_name="value")
        df_long["CR"]    = df_long["CR"].astype(float)
        df_long["value"] = pd.to_numeric(df_long["value"], errors="coerce")
        return df_long

    # ------------------------------------------------------------------
    # ALIGNEMENT & MÉTRIQUES
    # ------------------------------------------------------------------
    def _align(self, df_ref: pd.DataFrame, df_val: pd.DataFrame, key=None) -> pd.DataFrame:
        merged = self._to_long(df_ref).merge(
            self._to_long(df_val), on=["R", "CR"], how="outer",
            suffixes=("_ref", "_val"),
        ).sort_values(["R", "CR"])

        if key:
            self._aligned_cache[key] = merged
        return merged

    def _compute_metrics(self, merged: pd.DataFrame) -> dict:
        mask = merged["value_ref"].notna() & merged["value_val"].notna()
        diff = np.abs(merged.loc[mask, "value_val"] - merged.loc[mask, "value_ref"])

        if len(diff) == 0:
            return {"max_diff": np.nan, "mean_diff": np.nan, "rmse": np.nan,
                    "p95_diff": np.nan, "pass_rate": np.nan, "n_points": 0, "valid": False}

        return {
            "max_diff":  diff.max(),
            "mean_diff": diff.mean(),
            "rmse":      np.sqrt((diff ** 2).mean()),
            "p95_diff":  np.percentile(diff, 95),
            "pass_rate": float((diff < self.tol).mean()),
            "n_points":  int(mask.sum()),
            "valid":     bool((diff < self.tol).all()),
        }

    # ------------------------------------------------------------------
    # CHARGEMENT PARALLÈLE (interne)
    # ------------------------------------------------------------------
    def _load_pair(self, key, val_info, ref_info) -> dict | None:
        try:
            df_ref = self._load_and_standardize(ref_info["path"])
            df_val = self._load_and_standardize(val_info["path"])
            merged  = self._align(df_ref, df_val, key)
            metrics = self._compute_metrics(merged)
            return {"sn": key[0], "metric": key[1],
                    "plant": val_info["plant"], "pn": val_info["pn"],
                    "operation": val_info["operation"], **metrics}
        except Exception as exc:
            log.warning("Erreur sur %s/%s : %s", key[0], key[1], exc)
            return None

    # ------------------------------------------------------------------
    # PIPELINE DE VALIDATION
    # ------------------------------------------------------------------
    def run_validation(self) -> pd.DataFrame:
        pairs = [
            (key, self.tovalid_index[key], self.ref_index[key])
            for key in self.tovalid_index
            if key in self.ref_index
        ]
        log.info("Validation de %d paires (workers=%d)…", len(pairs), self.n_workers)

        results = []
        with ThreadPoolExecutor(max_workers=self.n_workers) as pool:
            futures = {pool.submit(self._load_pair, *p): p[0] for p in pairs}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Validation"):
                row = fut.result()
                if row:
                    results.append(row)

        self.results = pd.DataFrame(results)
        log.info(
            "Validation terminée — %d SN traités | pass rate global %.1f%%",
            len(self.results),
            self.results["pass_rate"].mean() * 100 if len(self.results) else 0,
        )
        return self.results

    # ------------------------------------------------------------------
    # STATISTIQUES DATASET
    # ------------------------------------------------------------------
    def build_dataset_stats(self) -> pd.DataFrame:
        def _to_df(index):
            return pd.DataFrame([
                {"sn": sn, "metric": m, "plant": i["plant"],
                 "pn": i["pn"], "operation": i["operation"]}
                for (sn, m), i in index.items()
            ])

        df_ref = _to_df(self.ref_index)
        df_val = _to_df(self.tovalid_index)

        grp = ["plant", "pn", "operation", "metric"]
        ref_g = df_ref.groupby(grp)["sn"].nunique().reset_index(name="n_ref")
        val_g = df_val.groupby(grp)["sn"].nunique().reset_index(name="n_tovalid")

        stats = ref_g.merge(val_g, on=grp, how="left").fillna(0)
        stats["coverage_ratio"] = stats["n_tovalid"] / stats["n_ref"]
        self.dataset_stats = stats
        return stats

    # ------------------------------------------------------------------
    # SAUVEGARDE
    # ------------------------------------------------------------------
    def _save_fig(self, fig, name: str, register: bool = True):
        base = self.output_dir / name
        fig.write_html(str(base) + ".html")
        try:
            fig.write_image(str(base) + ".png", scale=2, width=1200, height=700)
        except Exception:
            log.debug("kaleido non disponible — PNG ignoré pour %s", name)
        if register:
            self._figures.append({"name": name, "fig": fig})

    # ==================================================================
    # VISUALISATIONS
    # ==================================================================

    # ---- 1. Volume REF vs TOVALID ------------------------------------
    def plot_volume(self):
        df = self.dataset_stats.melt(
            id_vars=["plant", "pn", "operation", "metric"],
            value_vars=["n_ref", "n_tovalid"],
            var_name="Dataset",
            value_name="Nombre de SN",
        )
        df["Dataset"] = df["Dataset"].map({"n_ref": "REF", "n_tovalid": "TOVALID"})

        fig = px.bar(
            df, x="metric", y="Nombre de SN", color="Dataset",
            barmode="group",
            facet_col="plant", facet_row="pn",
            color_discrete_map={"REF": PALETTE["primary"], "TOVALID": PALETTE["secondary"]},
            category_orders={"Dataset": ["REF", "TOVALID"]},
        )
        _apply_theme(fig, "Volume de données — REF vs TOVALID", "Métrique", "Nombre de SN")
        fig.update_traces(marker_line_width=0)
        self._save_fig(fig, "01_volume_ref_vs_tovalid")
        fig.show()

    # ---- 2. CDF des erreurs max_diff ---------------------------------
    def plot_cdf_error(self):
        fig = px.ecdf(
            self.results.dropna(subset=["max_diff"]),
            x="max_diff", color="metric",
            color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["danger"]],
            markers=False, lines=True,
        )
        fig.add_vline(
            x=self.tol, line_dash="dash", line_color=PALETTE["danger"],
            annotation_text=f"Tolérance = {self.tol}",
            annotation_position="top right",
            annotation_font_color=PALETTE["danger"],
        )
        _apply_theme(
            fig,
            "Distribution cumulée des erreurs max (CDF)",
            "Erreur max absolue",
            "Proportion de SN",
        )
        self._save_fig(fig, "02_cdf_erreurs")
        fig.show()

    # ---- 3. Violin / Box distribution des erreurs -------------------
    def plot_error_distribution(self):
        df = self.results.dropna(subset=["max_diff", "mean_diff", "rmse"])
        df_m = df.melt(
            id_vars=["metric", "plant"],
            value_vars=["max_diff", "mean_diff", "rmse", "p95_diff"],
            var_name="Indicateur", value_name="Valeur",
        )
        labels = {"max_diff": "Max |Δ|", "mean_diff": "Mean |Δ|",
                  "rmse": "RMSE", "p95_diff": "P95 |Δ|"}
        df_m["Indicateur"] = df_m["Indicateur"].map(labels)

        fig = px.violin(
            df_m, x="Indicateur", y="Valeur", color="metric", box=True,
            points=False,
            color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["danger"]],
        )
        fig.add_hline(
            y=self.tol, line_dash="dot", line_color=PALETTE["warning"],
            annotation_text=f"Seuil {self.tol}",
        )
        _apply_theme(fig, "Distribution des indicateurs d'erreur par métrique",
                     "Indicateur", "Valeur")
        self._save_fig(fig, "03_distribution_erreurs")
        fig.show()

    # ---- 4. Pass rate par groupe (plant × pn × metric) --------------
    def plot_pass_rate_heatmap(self):
        grp = self.results.groupby(["plant", "pn", "metric"])["valid"].mean().reset_index()
        grp["pass_rate_%"] = grp["valid"] * 100
        grp["label"] = grp["plant"] + "\n" + grp["pn"]

        pivot = grp.pivot_table(index="label", columns="metric", values="pass_rate_%")

        fig = px.imshow(
            pivot,
            color_continuous_scale=["#EF4444", "#FBBF24", "#10B981"],
            zmin=0, zmax=100,
            text_auto=".1f",
            aspect="auto",
        )
        _apply_theme(fig, "Pass rate (%) par groupe — plant × PN × métrique",
                     "Métrique", "Groupe")
        fig.update_coloraxes(colorbar_title="Pass rate %")
        self._save_fig(fig, "04_pass_rate_heatmap")
        fig.show()

    # ---- 5. Ranking des pires SN ------------------------------------
    def plot_worst_sn(self, n: int = 20):
        df = self.results.sort_values("max_diff", ascending=False).head(n).copy()
        df["label"] = df["sn"] + " / " + df["metric"]

        fig = px.bar(
            df, x="max_diff", y="label", orientation="h",
            color="metric",
            color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["danger"]],
            hover_data=["plant", "pn", "mean_diff", "rmse", "pass_rate"],
        )
        fig.add_vline(
            x=self.tol, line_dash="dash", line_color=PALETTE["danger"],
            annotation_text=f"Tol={self.tol}",
        )
        _apply_theme(fig, f"Top {n} — pires SN par erreur max",
                     "Erreur max absolue", "SN / Métrique")
        fig.update_layout(yaxis=dict(autorange="reversed"))
        self._save_fig(fig, "05_worst_sn_ranking")
        fig.show()

    # ---- 6. Corrélation inter-métriques -----------------------------
    def plot_metric_correlation(self):
        pivot = self.results.pivot_table(
            index="sn", columns="metric", values="max_diff"
        )
        pivot = pivot.dropna()

        if pivot.shape[1] < 2:
            log.warning("Pas assez de métriques pour la corrélation.")
            return

        corr = pivot.corr()
        fig = px.imshow(
            corr, text_auto=".2f",
            color_continuous_scale="RdBu_r",
            zmin=-1, zmax=1,
        )
        _apply_theme(fig, "Corrélation de l'erreur max entre métriques", "", "")
        self._save_fig(fig, "06_correlation_metriques")
        fig.show()

    # ---- 7. Scatter REF vs TOVALID pour un SN donné ----------------
    def plot_scatter_ref_val(self, sn: str, metric: str):
        key    = (sn, metric)
        merged = self._aligned_cache.get(key)
        if merged is None:
            log.error("Clé %s non trouvée dans le cache. Lancez run_validation() d'abord.", key)
            return

        df = merged.dropna(subset=["value_ref", "value_val"]).copy()
        vmin = min(df["value_ref"].min(), df["value_val"].min())
        vmax = max(df["value_ref"].max(), df["value_val"].max())

        fig = px.scatter(
            df, x="value_ref", y="value_val",
            color=np.abs(df["value_val"] - df["value_ref"]),
            color_continuous_scale="RdYlGn_r",
            hover_data=["R", "CR"],
        )
        fig.add_shape(type="line", x0=vmin, y0=vmin, x1=vmax, y1=vmax,
                      line=dict(color=PALETTE["primary"], dash="dot"))
        fig.update_coloraxes(colorbar_title="|Δ|")
        _apply_theme(fig, f"Scatter REF vs TOVALID — {sn} / {metric}",
                     "Valeur REF", "Valeur TOVALID")
        self._save_fig(fig, f"07_scatter_{sn}_{metric}")
        fig.show()

    # ---- 8. Heatmap de diff pour un SN ------------------------------
    def plot_diff_heatmap(self, sn: str, metric: str):
        key    = (sn, metric)
        merged = self._aligned_cache.get(key)
        if merged is None:
            log.error("Clé %s non trouvée. Lancez run_validation() d'abord.", key)
            return

        df          = merged.copy()
        df["diff"]  = df["value_val"] - df["value_ref"]
        pivot       = df.pivot_table(index="R", columns="CR", values="diff")
        abs_max     = np.nanmax(np.abs(pivot.values))

        fig = px.imshow(
            pivot,
            color_continuous_scale="RdBu",
            zmin=-abs_max, zmax=abs_max,
            aspect="auto",
        )
        _apply_theme(fig, f"Heatmap Δ (TOVALID − REF) — {sn} / {metric}", "CR", "R")
        fig.update_coloraxes(colorbar_title="Δ valeur")
        self._save_fig(fig, f"08_diff_heatmap_{sn}_{metric}")
        fig.show()

    # ---- 9. Heatmap de diff agrégée (max sur groupe) ----------------
    def build_group_heatmap(self, plant: str, pn: str, metric: str):
        subset = self.results[
            (self.results["plant"] == plant) &
            (self.results["pn"]    == pn)    &
            (self.results["metric"] == metric)
        ]
        if subset.empty:
            log.warning("Aucun résultat pour %s|%s|%s", plant, pn, metric)
            return

        all_data = []
        for _, row in subset.iterrows():
            merged = self._aligned_cache.get((row["sn"], metric))
            if merged is None:
                continue
            temp         = merged.copy()
            temp["diff"] = np.abs(temp["value_val"] - temp["value_ref"])
            all_data.append(temp[["R", "CR", "diff"]])

        if not all_data:
            return

        agg   = pd.concat(all_data).groupby(["R", "CR"])["diff"].max().reset_index()
        pivot = agg.pivot_table(index="R", columns="CR", values="diff")

        fig = px.imshow(
            pivot,
            color_continuous_scale="RdYlGn_r",
            aspect="auto",
        )
        _apply_theme(fig, f"Max |Δ| agrégé — {plant.upper()} | {pn} | {metric}", "CR", "R")
        fig.update_coloraxes(colorbar_title="Max |Δ|")
        self._save_fig(fig, f"09_group_heatmap_{plant}_{pn}_{metric}")
        fig.show()

    # ---- 10. Heatmap de fail rate -----------------------------------
    def plot_group_fail_heatmap(self, plant: str, pn: str, metric: str):
        subset = self.results[
            (self.results["plant"] == plant) &
            (self.results["pn"]    == pn)    &
            (self.results["metric"] == metric)
        ]
        if subset.empty:
            return

        all_data = []
        for _, row in subset.iterrows():
            merged = self._aligned_cache.get((row["sn"], metric))
            if merged is None:
                continue
            temp         = merged.copy()
            temp["fail"] = np.abs(temp["value_val"] - temp["value_ref"]) > self.tol
            all_data.append(temp[["R", "CR", "fail"]])

        if not all_data:
            return

        fail_rate = pd.concat(all_data).groupby(["R", "CR"])["fail"].mean().reset_index()
        pivot     = fail_rate.pivot_table(index="R", columns="CR", values="fail")

        fig = px.imshow(
            pivot,
            color_continuous_scale=["#10B981", "#FBBF24", "#EF4444"],
            zmin=0, zmax=1,
            aspect="auto",
        )
        _apply_theme(fig, f"Taux d'échec (> {self.tol}) — {plant.upper()} | {pn} | {metric}",
                     "CR", "R")
        fig.update_coloraxes(colorbar_title="Fail rate")
        self._save_fig(fig, f"10_fail_heatmap_{plant}_{pn}_{metric}")
        fig.show()

    # ---- 11. Coverage heatmap ----------------------------------------
    def plot_group_coverage(self, plant: str, pn: str, metric: str):
        subset = self.results[
            (self.results["plant"] == plant) &
            (self.results["pn"]    == pn)    &
            (self.results["metric"] == metric)
        ]
        if subset.empty:
            return

        all_data = []
        for _, row in subset.iterrows():
            merged = self._aligned_cache.get((row["sn"], metric))
            if merged is None:
                continue
            temp          = merged.copy()
            temp["valid"] = temp["value_ref"].notna() & temp["value_val"].notna()
            all_data.append(temp[["R", "CR", "valid"]])

        if not all_data:
            return

        cov   = pd.concat(all_data).groupby(["R", "CR"])["valid"].mean().reset_index()
        pivot = cov.pivot_table(index="R", columns="CR", values="valid")

        fig = px.imshow(
            pivot,
            color_continuous_scale=["#EF4444", "#FBBF24", "#10B981"],
            zmin=0, zmax=1,
            aspect="auto",
        )
        _apply_theme(fig, f"Couverture des points — {plant.upper()} | {pn} | {metric}",
                     "CR", "R")
        fig.update_coloraxes(colorbar_title="Coverage")
        self._save_fig(fig, f"11_coverage_{plant}_{pn}_{metric}")
        fig.show()

    # ---- 12. Density de points par SN --------------------------------
    def plot_point_density(self):
        rows = [
            {"sn": k[0], "metric": k[1], "n_points": m["value_ref"].notna().sum()}
            for k, m in self._aligned_cache.items()
        ]
        if not rows:
            return

        fig = px.box(
            pd.DataFrame(rows), x="metric", y="n_points",
            color="metric",
            color_discrete_sequence=[PALETTE["primary"], PALETTE["secondary"], PALETTE["danger"]],
            points="outliers",
        )
        _apply_theme(fig, "Densité de points par SN et par métrique",
                     "Métrique", "Nombre de points communs")
        self._save_fig(fig, "12_point_density")
        fig.show()

    # ---- 13. Résumé statistique global (tableau) --------------------
    def print_summary(self):
        if self.results is None or self.results.empty:
            log.warning("Aucun résultat à résumer.")
            return

        log.info("\n%s", "=" * 60)
        log.info("RÉSUMÉ GLOBAL")
        log.info("=" * 60)

        total  = len(self.results)
        passed = self.results["valid"].sum()
        log.info("SN validés   : %d / %d  (%.1f%%)", passed, total, passed / total * 100)
        log.info("Tolérance    : %.2e", self.tol)

        for metric, grp in self.results.groupby("metric"):
            log.info(
                "  %-12s | max_diff p50=%.4f  p95=%.4f  p99=%.4f | pass=%.1f%%",
                metric,
                grp["max_diff"].quantile(0.50),
                grp["max_diff"].quantile(0.95),
                grp["max_diff"].quantile(0.99),
                grp["valid"].mean() * 100,
            )

        log.info("=" * 60)

    # ------------------------------------------------------------------
    # RAPPORT HTML DE SYNTHÈSE
    # ------------------------------------------------------------------
    def generate_report(self):
        """Génère un rapport HTML autonome avec toutes les figures."""
        if not self._figures:
            log.warning("Aucune figure à intégrer dans le rapport.")
            return

        ts    = datetime.now().strftime("%Y-%m-%d %H:%M")
        total = len(self.results) if self.results is not None else 0
        passed = int(self.results["valid"].sum()) if self.results is not None else 0
        pass_pct = passed / total * 100 if total else 0

        sections_html = ""
        for entry in self._figures:
            inner = entry["fig"].to_html(
                full_html=False, include_plotlyjs=False,
                config={"displayModeBar": True, "responsive": True},
            )
            sections_html += f"""
            <section class="chart-section">
              <div class="chart-wrap">{inner}</div>
            </section>"""

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Rapport de Validation Heatmap</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'IBM Plex Sans',Arial,sans-serif;background:#F8FAFC;color:#1E293B}}
    header{{background:#1E293B;color:#fff;padding:2rem 3rem}}
    header h1{{font-size:1.6rem;font-weight:700;margin-bottom:.4rem}}
    header p{{color:#94A3B8;font-size:.9rem}}
    .kpi-bar{{display:flex;gap:1.5rem;padding:1.5rem 3rem;background:#fff;
              border-bottom:1px solid #E2E8F0;flex-wrap:wrap}}
    .kpi{{flex:1;min-width:160px;background:#F1F5F9;border-radius:8px;
          padding:1rem 1.4rem}}
    .kpi .val{{font-size:2rem;font-weight:700;color:#2563EB}}
    .kpi .lbl{{font-size:.8rem;color:#64748B;margin-top:.2rem;text-transform:uppercase;
               letter-spacing:.05em}}
    main{{padding:2rem 3rem;display:grid;gap:2rem}}
    .chart-section{{background:#fff;border-radius:12px;padding:1.5rem;
                    box-shadow:0 1px 4px rgba(0,0,0,.06)}}
    footer{{text-align:center;padding:1.5rem;color:#94A3B8;font-size:.8rem;
            border-top:1px solid #E2E8F0}}
  </style>
</head>
<body>
<header>
  <h1>📊 Rapport de Validation Heatmap</h1>
  <p>Généré le {ts} — Tolérance : {self.tol}</p>
</header>
<div class="kpi-bar">
  <div class="kpi"><div class="val">{total}</div><div class="lbl">SN comparés</div></div>
  <div class="kpi"><div class="val">{passed}</div><div class="lbl">SN valides</div></div>
  <div class="kpi"><div class="val">{pass_pct:.1f}%</div><div class="lbl">Pass rate global</div></div>
  <div class="kpi"><div class="val">{self.tol}</div><div class="lbl">Seuil tolérance</div></div>
</div>
<main>
{sections_html}
</main>
<footer>HeatmapValidator v2 — Anthropic / Jordan Ngucho</footer>
</body>
</html>"""

        report_path = self.output_dir / "rapport_validation.html"
        report_path.write_text(html, encoding="utf-8")
        log.info("Rapport HTML généré → %s", report_path)


# ===========================================================================
# ENTRY POINT
# ===========================================================================
def main():
    REF_PATH     = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\data_validation\heatmap"
    TOVALID_PATH = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\data_validation\predict"
    OUTPUT_DIR   = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\plots"

    # ------------------------------------------------------------------
    validator = HeatmapValidator(
        ref_path=REF_PATH,
        tovalid_path=TOVALID_PATH,
        tol=1e-2,
        output_dir=OUTPUT_DIR,
        n_workers=8,
    )

    # 1. Indexation
    validator.build_index()

    # 2. Statistiques dataset
    stats = validator.build_dataset_stats()
    log.info("Dataset stats :\n%s", stats.to_string(index=False))
    validator.plot_volume()

    # 3. Validation (parallèle)
    validator.run_validation()

    # 4. Résumé console
    validator.print_summary()

    # 5. Visualisations globales
    validator.plot_cdf_error()
    validator.plot_error_distribution()
    validator.plot_pass_rate_heatmap()
    validator.plot_worst_sn(n=20)
    validator.plot_metric_correlation()
    validator.plot_point_density()

    # 6. Analyses par groupe
    PLANTS  = ["wtc", "czt", "mlx", "agb"]
    PNS     = ["362-850-019", "364-850-009"]
    METRICS = ["chord", "widthness", "tangent"]

    for plant in PLANTS:
        for pn in PNS:
            for metric in METRICS:
                subset = validator.results[
                    (validator.results["plant"]  == plant) &
                    (validator.results["pn"]     == pn)    &
                    (validator.results["metric"] == metric)
                ]
                if subset.empty:
                    continue
                log.info("Analyse groupe : %s | %s | %s", plant, pn, metric)
                validator.build_group_heatmap(plant, pn, metric)
                validator.plot_group_coverage(plant, pn, metric)
                validator.plot_group_fail_heatmap(plant, pn, metric)

    # 7. Exemples heatmap individuelle (premiers résultats disponibles)
    if not validator.results.empty:
        row = validator.results.iloc[0]
        validator.plot_diff_heatmap(row["sn"], row["metric"])
        validator.plot_scatter_ref_val(row["sn"], row["metric"])

    # 8. Rapport HTML final
    validator.generate_report()


if __name__ == "__main__":
    main()
