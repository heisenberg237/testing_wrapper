"""
HeatmapValidator v3 — Canvas unique de variation normalisée
============================================================

Visualisation principale :
  - Grille de sous-graphes : lignes = plants, colonnes = PNs
  - Chaque case = heatmap (axe X : SN, axe Y : métrique)
  - Valeur = max(|TOVALID − REF|) sur tous les points (R,CR) du SN
             normalisée par max(valeur REF) pour ce triplet métrique × plant × PN
  - Colormap commune 0 → 1 (variation relative en % si ×100)

Dépendances : pandas, numpy, matplotlib, seaborn, tqdm
"""

import re
import logging
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from tqdm import tqdm

warnings.filterwarnings("ignore", category=FutureWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("HeatmapValidator")


# ───────────────────────────────────────────────────────────────────────────────
# CLASSE
# ───────────────────────────────────────────────────────────────────────────────
class HeatmapValidator:

    SN_REGEX = re.compile(r"[A-Za-z]{2}\d{6}-[A-Za-z0-9]")
    METRICS  = ["chord", "widthness", "tangent"]

    def __init__(
        self,
        ref_path: str,
        tovalid_path: str,
        tol: float = 1e-2,
        output_dir: str = "plots",
        n_workers: int = 8,
    ):
        self.ref_path     = Path(ref_path)
        self.tovalid_path = Path(tovalid_path)
        self.tol          = tol
        self.n_workers    = n_workers
        self.output_dir   = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ref_index:    dict = {}
        self.tovalid_index: dict = {}
        self.results:      pd.DataFrame | None = None

    # ── Extraction ────────────────────────────────────────────────────────────
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

    # ── Indexation ────────────────────────────────────────────────────────────
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
        log.info("Indexation REF    → %s", self.ref_path)
        self.ref_index = self._index_files(self.ref_path)
        log.info("  %d fichiers", len(self.ref_index))

        log.info("Indexation TOVALID → %s", self.tovalid_path)
        self.tovalid_index = self._index_files(self.tovalid_path)
        log.info("  %d fichiers", len(self.tovalid_index))

    # ── Chargement ────────────────────────────────────────────────────────────
    def _load(self, path: Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        df = df.rename(columns={df.columns[0]: "R"}).dropna(how="all")
        df["R"] = df["R"].astype(str).str.extract(r"(\d+\.?\d*)")[0].astype(float)

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
        out = df.melt(id_vars="R", var_name="CR", value_name="value")
        out["CR"]    = out["CR"].astype(float)
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        return out

    # ── Calcul d'une paire ────────────────────────────────────────────────────
    def _process_pair(self, key, val_info, ref_info) -> dict | None:
        try:
            ref_long = self._to_long(self._load(ref_info["path"]))
            val_long = self._to_long(self._load(val_info["path"]))

            merged = ref_long.merge(val_long, on=["R", "CR"], suffixes=("_ref", "_val"))
            mask   = merged["value_ref"].notna() & merged["value_val"].notna()

            if mask.sum() == 0:
                return None

            diff       = np.abs(merged.loc[mask, "value_val"] - merged.loc[mask, "value_ref"])
            max_diff   = diff.max()
            ref_values = merged.loc[mask, "value_ref"].abs()
            max_ref    = ref_values.max()

            return {
                "sn":      key[0],
                "metric":  key[1],
                "plant":   val_info["plant"],
                "pn":      val_info["pn"],
                "max_diff": max_diff,
                "max_ref":  max_ref,        # sera utilisé pour normaliser par groupe
            }
        except Exception as exc:
            log.warning("Erreur %s/%s : %s", key[0], key[1], exc)
            return None

    # ── Pipeline ──────────────────────────────────────────────────────────────
    def run(self) -> pd.DataFrame:
        pairs = [
            (key, self.tovalid_index[key], self.ref_index[key])
            for key in self.tovalid_index
            if key in self.ref_index
        ]
        log.info("Calcul de %d paires (workers=%d)…", len(pairs), self.n_workers)

        rows = []
        with ThreadPoolExecutor(max_workers=self.n_workers) as pool:
            futures = {pool.submit(self._process_pair, *p): p[0] for p in pairs}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Validation"):
                row = fut.result()
                if row:
                    rows.append(row)

        self.results = pd.DataFrame(rows)

        # ── Normalisation : max(REF) par métrique × plant × PN ──────────────
        grp_max_ref = (
            self.results
            .groupby(["metric", "plant", "pn"])["max_ref"]
            .max()
            .rename("group_max_ref")
        )
        self.results = self.results.join(
            grp_max_ref, on=["metric", "plant", "pn"]
        )
        self.results["norm_diff"] = (
            self.results["max_diff"] / self.results["group_max_ref"]
        ).clip(upper=1.0)  # cap à 100 % pour l'échelle couleur

        log.info("Résultats : %d lignes", len(self.results))
        return self.results

    # ── Visualisation principale ───────────────────────────────────────────────
    def plot_canvas(self, save: bool = True):
        """
        Canvas unique :
          - Lignes  = plants  (ordre alphabétique)
          - Colonnes = PNs    (ordre alphabétique)
          - Chaque heatmap : axe X = SN (trié par erreur moyenne décroissante),
                             axe Y = métrique
          - Couleur = norm_diff  (0 → vert, 1 → rouge)
          - Ligne de tolérance normalisée annotée
        """
        if self.results is None:
            raise RuntimeError("Lance run() avant plot_canvas().")

        plants = sorted(self.results["plant"].dropna().unique())
        pns    = sorted(self.results["pn"].dropna().unique())
        n_rows = len(plants)
        n_cols = len(pns)

        FIG_W  = max(6 * n_cols, 10)
        FIG_H  = max(3.5 * n_rows, 5)

        fig, axes = plt.subplots(
            n_rows, n_cols,
            figsize=(FIG_W, FIG_H),
            squeeze=False,
        )
        fig.patch.set_facecolor("#F8FAFC")

        # Palette commune
        cmap   = sns.color_palette("RdYlGn_r", as_cmap=True)
        vmin, vmax = 0.0, 1.0

        # ── Remplissage des sous-graphes ─────────────────────────────────────
        for r, plant in enumerate(plants):
            for c, pn in enumerate(pns):
                ax = axes[r][c]
                ax.set_facecolor("#F1F5F9")

                subset = self.results[
                    (self.results["plant"] == plant) &
                    (self.results["pn"]    == pn)
                ]

                if subset.empty:
                    ax.text(
                        0.5, 0.5, "Pas de données",
                        ha="center", va="center",
                        transform=ax.transAxes,
                        color="#94A3B8", fontsize=9,
                    )
                    ax.set_xticks([]); ax.set_yticks([])
                    _label_axes(ax, plant, pn, r, c, n_rows, n_cols, plants, pns)
                    continue

                # Pivot : SN × métrique → norm_diff
                pivot = subset.pivot_table(
                    index="metric", columns="sn", values="norm_diff"
                )

                # Trier les SN par erreur moyenne décroissante (pires à gauche)
                sn_order = pivot.mean(axis=0).sort_values(ascending=False).index
                pivot    = pivot[sn_order]

                # Heatmap
                sns.heatmap(
                    pivot,
                    ax=ax,
                    cmap=cmap,
                    vmin=vmin, vmax=vmax,
                    linewidths=0.3,
                    linecolor="#E2E8F0",
                    cbar=False,
                    annot=(pivot.shape[1] <= 20),   # annotations si peu de SN
                    fmt=".2f",
                    annot_kws={"size": 7},
                    xticklabels=True,
                    yticklabels=True,
                )

                # Ligne de tolérance normalisée (pour référence visuelle)
                # max_ref du groupe → tol / group_max_ref
                for metric in pivot.index:
                    gmr = subset.loc[
                        subset["metric"] == metric, "group_max_ref"
                    ].max()
                    if gmr and gmr > 0:
                        tol_norm = min(self.tol / gmr, 1.0)
                        # on ne dessine pas de ligne par métrique ici
                        # (serait illisible), on annote le titre à la place

                # Axes labels
                ax.set_xlabel("")
                ax.set_ylabel("")
                ax.tick_params(axis="x", labelsize=6, rotation=45, labelcolor="#475569")
                ax.tick_params(axis="y", labelsize=8, rotation=0,  labelcolor="#1E293B")

                _label_axes(ax, plant, pn, r, c, n_rows, n_cols, plants, pns)

        # ── Colorbar commune ─────────────────────────────────────────────────
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=100))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=axes, fraction=0.015, pad=0.02, aspect=40)
        cbar.set_label("Variation relative max  (%)", fontsize=10, labelpad=10)
        cbar.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
        cbar.ax.tick_params(labelsize=8)

        # ── Titre global ─────────────────────────────────────────────────────
        fig.suptitle(
            f"Variation normalisée  REF → TOVALID   "
            f"(tolérance = {self.tol})\n"
            "max|Δ| / max(REF)  par  métrique × plant × PN  —  SN triés par erreur décroissante",
            fontsize=11, fontweight="normal", color="#1E293B",
            y=1.01,
        )

        plt.tight_layout()

        if save:
            out_png  = self.output_dir / "variation_normalisee.png"
            out_html = self.output_dir / "variation_normalisee_interactive.html"
            fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
            log.info("PNG sauvegardé → %s", out_png)
            # version interactive via plotly (optionnel)
            try:
                _save_plotly_version(self.results, self.tol, out_html)
                log.info("HTML interactif → %s", out_html)
            except Exception as e:
                log.debug("Plotly non disponible : %s", e)

        plt.show()
        return fig


# ── Helpers ───────────────────────────────────────────────────────────────────
def _label_axes(ax, plant, pn, r, c, n_rows, n_cols, plants, pns):
    """Titres de lignes (plant) et colonnes (PN) en bord de grille."""
    if r == 0:
        ax.set_title(f"PN : {pn}", fontsize=9, fontweight="normal",
                     color="#0C447C", pad=6)
    if c == 0:
        ax.set_ylabel(
            plant.upper(), fontsize=9, fontweight="normal",
            color="#0C447C", labelpad=8,
        )


def _save_plotly_version(results: pd.DataFrame, tol: float, path: Path):
    """Version interactive Plotly du même canvas (optionnel)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    plants = sorted(results["plant"].dropna().unique())
    pns    = sorted(results["pn"].dropna().unique())

    fig = make_subplots(
        rows=len(plants), cols=len(pns),
        subplot_titles=[
            f"{pl.upper()} | {pn}"
            for pl in plants for pn in pns
        ],
        horizontal_spacing=0.05,
        vertical_spacing=0.12,
    )

    for r, plant in enumerate(plants, 1):
        for c, pn in enumerate(pns, 1):
            subset = results[
                (results["plant"] == plant) &
                (results["pn"]    == pn)
            ]
            if subset.empty:
                continue

            pivot = subset.pivot_table(
                index="metric", columns="sn", values="norm_diff"
            )
            sn_order = pivot.mean(axis=0).sort_values(ascending=False).index
            pivot    = pivot[sn_order]

            fig.add_trace(
                go.Heatmap(
                    z=pivot.values * 100,
                    x=list(pivot.columns),
                    y=list(pivot.index),
                    colorscale="RdYlGn_r",
                    zmin=0, zmax=100,
                    showscale=(r == 1 and c == len(pns)),
                    colorbar=dict(
                        title="Variation (%)",
                        ticksuffix="%",
                        len=0.5,
                    ),
                    hovertemplate=(
                        "SN: %{x}<br>"
                        "Métrique: %{y}<br>"
                        "Variation: %{z:.1f}%<extra></extra>"
                    ),
                ),
                row=r, col=c,
            )

    fig.update_layout(
        title=dict(
            text=(
                f"Variation normalisée REF → TOVALID  (tol={tol})<br>"
                "<sup>max|Δ| / max(REF) par métrique × plant × PN — SN triés par erreur décroissante</sup>"
            ),
            x=0.5, xanchor="center", font=dict(size=14),
        ),
        height=350 * len(plants),
        paper_bgcolor="#F8FAFC",
        plot_bgcolor="#F8FAFC",
        font=dict(family="IBM Plex Sans, Arial", color="#1E293B"),
        margin=dict(t=100, b=60, l=80, r=80),
    )

    fig.write_html(str(path))


# ───────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ───────────────────────────────────────────────────────────────────────────────
def main():
    REF_PATH     = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\data_validation\heatmap"
    TOVALID_PATH = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\data_validation\predict"
    OUTPUT_DIR   = r"\\nas23\CEI_IX_BUROTIK1_m\Jordan_Ngucho\Heatmap_Validation\plots"

    v = HeatmapValidator(
        ref_path=REF_PATH,
        tovalid_path=TOVALID_PATH,
        tol=1e-2,
        output_dir=OUTPUT_DIR,
        n_workers=8,
    )

    v.build_index()
    v.run()
    v.plot_canvas(save=True)


if __name__ == "__main__":
    main()
