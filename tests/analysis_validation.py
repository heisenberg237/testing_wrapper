"""
postprocess_bolts.py
====================
Post-traitement des déformations plastiques des vis (brides de fût cylindrique)
à partir d'un fichier d3plot LS-DYNA, en utilisant le package lasso-python.

Fonctionnalités :
    - Chargement du d3plot (tous les fichiers d3plot* et le deck .k)
    - Filtrage des parts d'intérêt (vis) par part_id
    - Rognage des éléments dont la position Z des nœuds est inférieure à un seuil
    - Extraction de la déformation plastique effective au dernier pas de temps
    - Rapport trié par ordre décroissant de plasticité max par vis

Utilisation :
    Adapter la section "CONFIGURATION" en bas de ce fichier, puis :
        python postprocess_bolts.py

Dépendances :
    pip install lasso-python numpy

Références API lasso :
    https://open-lasso-python.github.io/lasso-python/dyna
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

# lasso-python — API publique LS-DYNA
from lasso.dyna import D3plot, ArrayType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_d3plot(d3plot_path: str | Path) -> D3plot:
    """Charge le fichier d3plot (+ tous les fichiers d3plot001, d3plot002, …).

    Parameters
    ----------
    d3plot_path:
        Chemin vers le fichier d3plot principal (ex: ``"./results/d3plot"``).

    Returns
    -------
    D3plot
        Objet lasso contenant toutes les données de la simulation.
    """
    path = Path(d3plot_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier d3plot introuvable : {path}")

    print(f"[INFO] Chargement du d3plot : {path}")
    d3 = D3plot(str(path))
    print(f"[INFO] Chargement terminé.")
    print(f"       Nombre de pas de temps : {len(d3.arrays[ArrayType.global_timesteps])}")
    return d3


def get_shell_part_ids(d3: D3plot) -> np.ndarray:
    """Retourne les part_ids uniques présents dans les éléments coques.

    Parameters
    ----------
    d3:
        Objet D3plot chargé.

    Returns
    -------
    np.ndarray
        Tableau 1-D des part_ids présents dans les coques.
    """
    shell_part_ids = d3.arrays[ArrayType.element_shell_part_indexes]
    # Les part indexes sont des indices 0-based dans le tableau des parts
    part_ids_all = d3.arrays[ArrayType.part_ids]
    unique_part_ids = np.unique(part_ids_all[np.unique(shell_part_ids)])
    return unique_part_ids


def filter_shells_by_parts(
    d3: D3plot,
    target_part_ids: list[int],
) -> tuple[np.ndarray, np.ndarray]:
    """Retourne les indices globaux des éléments coques appartenant aux parts cibles.

    Parameters
    ----------
    d3:
        Objet D3plot chargé.
    target_part_ids:
        Liste des part_ids des vis à analyser.

    Returns
    -------
    shell_indices : np.ndarray
        Indices (0-based) des éléments coques filtrés dans les tableaux d3plot.
    element_ids : np.ndarray
        IDs LS-DYNA correspondants de ces éléments.
    """
    all_part_ids = d3.arrays[ArrayType.part_ids]           # (n_parts,)
    shell_part_idx = d3.arrays[ArrayType.element_shell_part_indexes]  # (n_shells,)
    shell_ids = d3.arrays[ArrayType.element_shell_ids]     # (n_shells,)

    # Construire un mapping part_id → part_index local
    part_id_to_idx = {pid: i for i, pid in enumerate(all_part_ids)}

    # Indices locaux des parts cibles
    target_part_indices = set()
    for pid in target_part_ids:
        if pid not in part_id_to_idx:
            print(f"[WARN] part_id={pid} introuvable dans le modèle — ignoré.")
        else:
            target_part_indices.add(part_id_to_idx[pid])

    # Masque sur les éléments coques
    mask = np.isin(shell_part_idx, list(target_part_indices))
    shell_indices = np.where(mask)[0]
    element_ids = shell_ids[shell_indices]

    print(f"[INFO] {len(shell_indices)} éléments coques trouvés pour les parts {target_part_ids}.")
    return shell_indices, element_ids


def get_shell_node_coords_last_state(
    d3: D3plot,
    shell_indices: np.ndarray,
) -> np.ndarray:
    """Retourne les coordonnées moyennes en Z de chaque coque au dernier état.

    On utilise la position des nœuds au dernier pas de temps (ou initiale
    si les coordonnées déformées ne sont pas disponibles).

    Parameters
    ----------
    d3:
        Objet D3plot chargé.
    shell_indices:
        Indices globaux (0-based) des éléments coques d'intérêt.

    Returns
    -------
    np.ndarray, shape (n_shells_filtered,)
        Coordonnée Z moyenne de chaque élément.
    """
    # Connectivité coque : (n_shells, 4) nœuds par élément (Q4 ou T3 avec nœud dupliqué)
    shell_node_ids = d3.arrays[ArrayType.element_shell_node_indexes]  # indices de nœuds (0-based)

    # Coordonnées des nœuds : soit déformées (timestep), soit initiales
    if ArrayType.node_displacement in d3.arrays:
        node_coords_init = d3.arrays[ArrayType.node_coordinates]      # (n_nodes, 3)
        node_disp = d3.arrays[ArrayType.node_displacement]            # (n_timesteps, n_nodes, 3)
        node_coords = node_coords_init + node_disp[-1]                # dernier pas
    else:
        node_coords = d3.arrays[ArrayType.node_coordinates]           # (n_nodes, 3) — géométrie initiale

    # Nœuds des éléments filtrés
    shell_nodes = shell_node_ids[shell_indices]        # (n_filtered, 4)
    z_coords = node_coords[shell_nodes, 2]             # (n_filtered, 4)  — composante Z
    z_mean = z_coords.mean(axis=1)                     # (n_filtered,)

    return z_mean


def crop_shells_by_z(
    shell_indices: np.ndarray,
    element_ids: np.ndarray,
    z_mean: np.ndarray,
    z_threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Supprime les éléments dont la position Z moyenne est inférieure au seuil.

    Parameters
    ----------
    shell_indices, element_ids, z_mean:
        Sorties de ``filter_shells_by_parts`` et ``get_shell_node_coords_last_state``.
    z_threshold:
        Seuil en Z en dessous duquel les éléments sont exclus.

    Returns
    -------
    shell_indices_cropped, element_ids_cropped : np.ndarray
        Sous-ensemble conservé après rognage.
    """
    mask = z_mean >= z_threshold
    n_removed = np.sum(~mask)
    print(f"[INFO] Rognage Z < {z_threshold} : {n_removed} éléments supprimés, "
          f"{np.sum(mask)} éléments conservés.")
    return shell_indices[mask], element_ids[mask]


def extract_plastic_strain_last_state(
    d3: D3plot,
    shell_indices: np.ndarray,
) -> np.ndarray:
    """Extrait la déformation plastique effective au dernier pas de temps.

    LS-DYNA stocke la plasticité effective (effective plastic strain) dans
    ``element_shell_effective_plastic_strain``.  Si cette variable n'est pas
    disponible, une exception claire est levée.

    Parameters
    ----------
    d3:
        Objet D3plot chargé.
    shell_indices:
        Indices globaux (0-based) des éléments coques d'intérêt (après rognage).

    Returns
    -------
    np.ndarray, shape (n_shells_filtered,)
        Valeur scalaire de plasticité effective pour chaque élément au dernier pas.

    Notes
    -----
    Le tableau peut être de forme ``(n_timesteps, n_shells)`` ou
    ``(n_timesteps, n_shells, n_integration_points)``.  On prend le maximum
    sur les points d'intégration si nécessaire.
    """
    key = ArrayType.element_shell_effective_plastic_strain

    if key not in d3.arrays:
        raise KeyError(
            "La variable 'element_shell_effective_plastic_strain' est absente du d3plot.\n"
            "Vérifiez que DATABASE_EXTENT_BINARY STRFLG=1 est actif dans votre deck .k."
        )

    plastic_strain_all = d3.arrays[key]  # (n_timesteps, n_shells) ou (n_ts, n_shells, n_ip)

    # Dernier pas de temps
    eps_last = plastic_strain_all[-1]    # (n_shells,) ou (n_shells, n_ip)

    if eps_last.ndim == 2:
        # Plusieurs points d'intégration → valeur max sur les IP
        eps_last = eps_last.max(axis=-1)

    return eps_last[shell_indices]


def build_part_index_map(
    d3: D3plot,
    shell_indices: np.ndarray,
    target_part_ids: list[int],
) -> dict[int, np.ndarray]:
    """Construit un mapping part_id → indices locaux dans ``shell_indices``.

    Parameters
    ----------
    d3:
        Objet D3plot chargé.
    shell_indices:
        Indices globaux des éléments coques filtrés + rognés.
    target_part_ids:
        Liste des part_ids à analyser.

    Returns
    -------
    dict[int, np.ndarray]
        Clé = part_id, valeur = tableau des positions (0-based) dans shell_indices
        qui appartiennent à ce part_id.
    """
    all_part_ids = d3.arrays[ArrayType.part_ids]
    shell_part_idx = d3.arrays[ArrayType.element_shell_part_indexes]

    part_id_to_idx = {pid: i for i, pid in enumerate(all_part_ids)}

    mapping: dict[int, np.ndarray] = {}
    for pid in target_part_ids:
        if pid not in part_id_to_idx:
            continue
        local_part_idx = part_id_to_idx[pid]
        # Parmi les éléments filtrés, lesquels appartiennent à ce part ?
        local_positions = np.where(shell_part_idx[shell_indices] == local_part_idx)[0]
        mapping[pid] = local_positions

    return mapping


# ---------------------------------------------------------------------------
# Analyse principale
# ---------------------------------------------------------------------------

def analyse_bolt_plasticity(
    d3plot_path: str | Path,
    bolt_part_ids: list[int],
    z_threshold: float = 319.0,
    output_file: str | Path = "bolt_plasticity_report.txt",
) -> None:
    """Analyse complète des déformations plastiques des vis.

    Étapes :
        1. Chargement du d3plot.
        2. Filtrage des éléments coques appartenant aux vis.
        3. Rognage des éléments sous le seuil Z.
        4. Extraction de la plasticité effective au dernier pas de temps.
        5. Pour chaque vis : identification de l'élément max.
        6. Écriture du rapport trié par plasticité décroissante.

    Parameters
    ----------
    d3plot_path:
        Chemin vers le fichier d3plot principal.
    bolt_part_ids:
        Liste des part_ids des vis à analyser.
    z_threshold:
        Seuil de rognage en Z (les éléments sous ce seuil sont exclus).
    output_file:
        Chemin du fichier texte de sortie.
    """
    # -- 1. Chargement -------------------------------------------------------
    d3 = load_d3plot(d3plot_path)

    # -- 2. Filtrage par part_id ---------------------------------------------
    shell_indices, element_ids = filter_shells_by_parts(d3, bolt_part_ids)

    if len(shell_indices) == 0:
        print("[ERROR] Aucun élément coque trouvé pour les parts spécifiées. Abandon.")
        return

    # -- 3. Rognage en Z -----------------------------------------------------
    z_mean = get_shell_node_coords_last_state(d3, shell_indices)
    shell_indices, element_ids = crop_shells_by_z(
        shell_indices, element_ids, z_mean, z_threshold
    )

    if len(shell_indices) == 0:
        print("[ERROR] Aucun élément conservé après rognage Z. Vérifiez le seuil.")
        return

    # -- 4. Plasticité au dernier pas de temps --------------------------------
    plastic_strain = extract_plastic_strain_last_state(d3, shell_indices)

    # -- 5. Mapping par vis ---------------------------------------------------
    part_map = build_part_index_map(d3, shell_indices, bolt_part_ids)

    # Récupère le dernier temps de simulation
    timesteps = d3.arrays[ArrayType.global_timesteps]
    last_time = float(timesteps[-1])

    # -- 6. Construction et écriture du rapport --------------------------------
    results: list[dict] = []

    for pid, local_pos in part_map.items():
        if len(local_pos) == 0:
            results.append({
                "part_id": pid,
                "max_plastic_strain": 0.0,
                "element_id_max": -1,
                "n_elements": 0,
            })
            continue

        part_strains = plastic_strain[local_pos]
        part_elem_ids = element_ids[local_pos]

        idx_max = int(np.argmax(part_strains))
        results.append({
            "part_id": pid,
            "max_plastic_strain": float(part_strains[idx_max]),
            "element_id_max": int(part_elem_ids[idx_max]),
            "n_elements": len(local_pos),
        })

    # Tri décroissant par plasticité max
    results.sort(key=lambda r: r["max_plastic_strain"], reverse=True)

    # Écriture du rapport
    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        header = (
            "=" * 70 + "\n"
            "  RAPPORT DE DÉFORMATION PLASTIQUE DES VIS — LS-DYNA\n"
            "=" * 70 + "\n"
            f"  Fichier d3plot   : {Path(d3plot_path).resolve()}\n"
            f"  Dernier temps    : {last_time:.6e} s\n"
            f"  Seuil de rognage : Z >= {z_threshold}\n"
            f"  Nombre de vis    : {len(bolt_part_ids)}\n"
            "=" * 70 + "\n\n"
        )
        f.write(header)
        print(header, end="")

        col_header = (
            f"{'Rang':<6} {'Part ID':<10} {'Plasticité max':<20} "
            f"{'Élément ID (max)':<20} {'N éléments':<12}\n"
        )
        separator = "-" * 70 + "\n"
        f.write(col_header)
        f.write(separator)
        print(col_header, end="")
        print(separator, end="")

        for rank, res in enumerate(results, start=1):
            line = (
                f"{rank:<6} {res['part_id']:<10} {res['max_plastic_strain']:<20.6e} "
                f"{res['element_id_max']:<20} {res['n_elements']:<12}\n"
            )
            f.write(line)
            print(line, end="")

        f.write("\n" + "=" * 70 + "\n")
        print("\n" + "=" * 70)

    print(f"\n[INFO] Rapport écrit dans : {output_path.resolve()}")


# ---------------------------------------------------------------------------
# CONFIGURATION — À ADAPTER AVANT EXÉCUTION
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # -----------------------------------------------------------------------
    # Chemin vers le fichier d3plot principal
    # (lasso charge automatiquement les fichiers d3plot001, d3plot002, … dans le
    #  même répertoire)
    # -----------------------------------------------------------------------
    D3PLOT_PATH = "./results/d3plot"

    # -----------------------------------------------------------------------
    # Liste des part_ids correspondant aux vis de la bride
    # Remplacer par vos vraies valeurs.
    # -----------------------------------------------------------------------
    BOLT_PART_IDS: list[int] = [
        101, 102, 103, 104, 105, 106,
        107, 108, 109, 110, 111, 112,
    ]

    # -----------------------------------------------------------------------
    # Seuil de rognage en Z :
    # Les éléments dont la coordonnée Z moyenne est INFÉRIEURE à cette valeur
    # sont exclus de l'analyse.
    # -----------------------------------------------------------------------
    Z_THRESHOLD: float = 319.0

    # -----------------------------------------------------------------------
    # Fichier de sortie du rapport
    # -----------------------------------------------------------------------
    OUTPUT_FILE = "bolt_plasticity_report.txt"

    # -----------------------------------------------------------------------
    # Lancement de l'analyse
    # -----------------------------------------------------------------------
    analyse_bolt_plasticity(
        d3plot_path=D3PLOT_PATH,
        bolt_part_ids=BOLT_PART_IDS,
        z_threshold=Z_THRESHOLD,
        output_file=OUTPUT_FILE,
    )
