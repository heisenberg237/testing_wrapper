# Documentation MLE Heatmap Wrapper

**Documentation complète du projet — méthodologie, usage et maintenance**

---

## Table des matières

1. [Vue d'ensemble — Qu'est-ce que ce projet ?](#1-vue-densemble--quest-ce-que-ce-projet-)
2. [Pourquoi ce projet existe-t-il ?](#2-pourquoi-ce-projet-existe-t-il-)
3. [Comment ça marche ? — Le workflow en pratique](#3-comment-ça-marche----le-workflow-en-pratique)
4. [Structure des données — Ce que nous attendons](#4-structure-des-données--ce-que-nous-attendons)
5. [Parsing des données — Logique métier par fournisseur](#5-parsing-des-données--logique-métier-par-fournisseur)
6. [Métriques calculées](#6-métriques-calculées)
7. [Configuration — Changer le comportement](#7-configuration--changer-le-comportement)
8. [Évolution et maintenance](#8-évolution-et-maintenance)

---

## 1. Vue d'ensemble — Qu'est-ce que ce projet ?

Le **MLE Heatmap Wrapper** est un outil qui transforme des **données de mesure métrologique** (points 3D issus de machines à mesurer) en **indicateurs géométriques exploitable** pour le contrôle qualité et l'analyse de MLEs.

En résumé :

- **Entrée** : dossiers contenant des fichiers ASCII (points X, Y, Z, etc.)
- **Traitement** : parsing, validation, calcul de métriques géométriques
- **Sortie** : fichiers CSV consolidés par pièce, utilisables pour les heatmaps et les rapports qualité

Le projet sert d'**orchestrateur** : il prépare les données, les valide, appelle les calculs, et exporte les résultats. Les calculs géométriques avancés proviennent d’un package externe (`calcul_geom_descr_mle`) ou de formules de repli intégrées.

---

## 2. Pourquoi ce projet existe-t-il ?

### Contexte métier

Plusieurs **fournisseurs** (CZT, MLX, TECT PA, etc.) livrent des données métrologiques dans des **formats différents**. Chaque fournisseur organise ses fichiers à sa manière, avec ses propres conventions de nommage et de structure. Le projet doit :

1. **Unifier** ces formats disparates vers un modèle commun.
2. **Calculer** des métriques géométriques identiques pour tous (widthness, tangent, épaisseurs, etc.).
3. **Produire** des exports CSV homogènes pour le pipeline heatmap (visualisation, suivi qualité).

### Choix de conception

| Choix | Raison |
|-------|--------|
| **Un dossier par pièce / numéro de série** | Permet de traiter des lots de pièces en batch, et d’identifier chaque pièce par son dossier. |
| **Dossier GEOM obligatoire** | Convention simple pour localiser les données géométriques, indépendamment du fournisseur. |
| **Parsing par fournisseur** | Chaque fournisseur a une logique métier spécifique : nombre de sections, nommage des fichiers, regroupement des points. Le parsing doit être adaptable. |
| **Format de sortie unique** | Un CSV par pièce avec colonnes normalisées (serial_number, supplier, section_label, metric_value, etc.) facilite l’alimentation du pipeline heatmap. |
| **Validation avant calcul** | Évite de lancer des calculs sur des données incomplètes ou incohérentes. |

---

## 3. Comment ça marche ? — Le workflow en pratique

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Dossier pièces │     │   Parsing +      │     │   Export CSV    │
│  data/in/mlx/   │ ──► │   Validation    │ ──► │   + métriques    │
│  .../GEOM/...   │     │   + Calculs      │     │   output/        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Étapes détaillées

1. **Sélection** : on choisit un couple `numéro de pièce` + `fournisseur` (ex. 362 + MLX).
2. **Découverte** : le programme parcourt le dossier d’entrée et détecte les dossiers de pièces (en cherchant le sous-dossier GEOM).
3. **Parsing** : pour chaque pièce, les fichiers GEOM sont lus et convertis en points (X, Y, Z) avec section et face (intrados/extrados).
4. **Validation** : vérification du nombre de sections, de la présence des deux faces, de la qualité des points.
5. **Calcul des métriques** : widthness, tangent, épaisseurs, etc.
6. **Export** : un CSV par pièce, nommé `{serial}_{supplier}_{part}_{date}.csv`.

### Utilisation en ligne de commande

**Mode batch (recommandé)** — traitement de plusieurs pièces :

```bash
mle-heatmap --input-dir data/in/mlx --part-number 362 --supplier MLX --output output --metrics widthness tangent
```

**Mode fichier unique (legacy)** — un seul CSV déjà normalisé :

```bash
mle-heatmap --input-file data/input.csv --part-number 362 --supplier CZT --output output
```

---

## 4. Structure des données — Ce que nous attendons

### Convention générale (indépendante du fournisseur)

La structure **commune** imposée est la suivante :

```
data/in/{fournisseur}/
└── {dossier_piece}/          ← Un dossier par pièce / numéro de série
    └── GEOM/                 ← Toujours présent, contient les données géométriques
        └── ...               ← Fichiers dont le format dépend du fournisseur
```

- **Dossier pièce** : identifie la pièce (ex. `362_850_019_6F9_INT_PC_JE407542-N_05022026_034232_ARCHIVE`).
- **GEOM** : sous-dossier obligatoire contenant les points de mesure.
- Le contenu exact (noms de fichiers, colonnes, extensions) **varie selon le fournisseur**.

### Exemple MLX

```
data/in/mlx/
└── 362_850_019_6F9_INT_PC_JE407542-N_05022026_034232_ARCHIVE/
    └── GEOM/
        ├── I03.MEA    ← Intrados, section 03
        ├── I05.MEA
        ├── ...
        ├── E03.MEA    ← Extrados, section 03
        └── ...
```

- **I** = intrados, **E** = extrados.
- Chaque fichier = une section (CR) à un Z donné.
- Format MEA : lignes `P  X  Y  Z  U  V  W` (point + coordonnées + vecteur normal).

### Exemple format alternatif (.xyz)

Certains fournisseurs livrent **deux fichiers** :

```
GEOM/
├── int.xyz    ← Tous les points intrados, toutes sections confondues
└── ext.xyz    ← Tous les points extrados, toutes sections confondues
```

- Chaque ligne = un point (X, Y, Z).
- Les sections (CR) sont **déduites** en regroupant les points ayant un Z identique ou proche.

Le parsing doit donc gérer ces deux cas (multi-fichiers MEA vs. deux fichiers XYZ).

---

## 5. Parsing des données — Logique métier par fournisseur

### Principe

Le parsing des données GEOM **dépend du fournisseur**. Chaque fournisseur a :

- une organisation des fichiers (multi-fichiers MEA, deux fichiers XYZ, etc.) ;
- des conventions de nommage (I03, E05, etc.) ;
- une façon de définir les **sections** (Cercle de Référence, CR) : par fichier ou par regroupement sur Z.

Le code est conçu pour que le **mainteneur** puisse écrire une logique de parsing **spécifique par fournisseur**.

### Architecture technique des parsers

- **BaseParser** : gère la structure commune (dossier pièce → GEOM, métadonnées, validation).
- **Parsers spécifiques** (MLXParser, CZTParser, TECTParser) : héritent de BaseParser et peuvent **surcharger** la méthode `_parse_geom_folder` pour implémenter leur logique propre.

### Format MLX (fichiers IXX.MEA / EXX.MEA)

- Fichiers : `I03.MEA`, `E05.MEA`, etc.
- **I** → intrados, **E** → extrados.
- Le numéro dans le nom (03, 05, …) = étiquette de section (CR).
- Chaque fichier contient les points à un Z donné ; ce Z définit la section.
- Colonnes utilisées : X, Y, Z (U, V, W optionnels).

### Format alternatif (deux fichiers .xyz)

- Fichiers : `int.xyz`, `ext.xyz`.
- Chaque ligne = X, Y, Z.
- **Regroupement par Z** : on regroupe les points dont le Z est identique (ou proche à une tolérance près). Chaque groupe forme une **section** (CR).
- Les sections sont numérotées automatiquement (ex. 01, 02, 03…).

### Parser XYZ (deux fichiers, regroupement par Z)

Le projet fournit `XYZFolderParser` pour les fournisseurs qui livrent :

- `int.xyz` : tous les points intrados
- `ext.xyz` : tous les points extrados

Les sections sont créées en regroupant les points ayant un Z identique ou proche (tolérance dans `supplier_settings.z_grouping_tolerance`).

Pour l’utiliser, créer une classe héritant de `XYZFolderParser` et l’enregistrer dans la CLI. Voir `parsers/xyz_parser.py` pour l’implémentation.

### Ajouter un nouveau fournisseur — Procédure détaillée

Procédure pas à pas pour intégrer un nouveau fournisseur.

#### Étape 1 — Analyser la structure des données

1. Obtenir un échantillon de données du fournisseur.
2. Vérifier que la structure respecte : `dossier_piece/GEOM/...`.
3. Identifier :
   - Organisation des fichiers (multi-fichiers par section ou quelques fichiers agrégés)
   - Extensions (.mea, .xyz, .csv, etc.)
   - Format des lignes (colonnes, séparateurs)
   - Comment sont définies les sections (CR) et les faces (int/ext)
   - Format du nom du dossier pièce (pour extraire n° série, date, etc.)

#### Étape 2 — Créer le parser

Créer un fichier `src/mle_heatmap_wrapper/parsers/mon_fournisseur_parser.py` :

```python
from pathlib import Path
import pandas as pd
from .base_parser import BaseParser
from ..models.data_models import InputData, PieceMetadata

class MonFournisseurParser(BaseParser):
    """Parser pour le fournisseur XYZ."""

    def parse(self, file_path: Path) -> InputData:
        """Mode legacy: fichier CSV unique."""
        df = self._load_csv(file_path)
        df = self._standardize_columns(df)
        self._validate_file_format(df)
        # ... appliquer les transformations métier
        return InputData(dataframe=df, part_config=self.part_config, metadata={})

    def _validate_file_format(self, df: pd.DataFrame) -> None:
        required = {"x", "y", "z", "section_label", "side"}
        if not required.issubset(df.columns):
            raise ValueError(f"Colonnes manquantes: {required - set(df.columns)}")

    # Si le format GEOM diffère du défaut (multi-fichiers IXX/EXX.MEA),
    # surcharger _parse_geom_folder :
    # def _parse_geom_folder(self, geom_folder: Path, piece_metadata: PieceMetadata):
    #     ...
```

- **Format GEOM identique au défaut** (fichiers I03.MEA, E05.MEA, etc.) : ne pas surcharger `_parse_geom_folder`, le comportement par défaut suffit.
- **Format alternatif** (ex. deux fichiers int.xyz / ext.xyz) : créer une classe héritant de `XYZFolderParser` ou surcharger `_parse_geom_folder`.

#### Étape 3 — Enregistrer le parser

Dans `src/mle_heatmap_wrapper/parsers/registry.py`, ajouter :

```python
from .mon_fournisseur_parser import MonFournisseurParser

PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    # ... existants ...
    "MonFournisseurParser": MonFournisseurParser,
}
```

#### Étape 4 — Configuration dans `config/parts_config.yaml`

Ajouter une entrée par couple (part_number, supplier) :

```yaml
- part_number: "362"
  supplier: "Mon Fournisseur"
  sections_count: 27
  piece_folder_regex: "^362_.*$"
  geom_folder_name: "GEOM"
  geom_file_extensions: [".mea", ".xyz"]
  geom_file_regex: "(?P<section_prefix>[IE])(?P<section>\\d{2})"
  folder_metadata_regex: "^(?P<part_number>\\d{3})_.*_(?P<serial_number>[A-Z0-9-]+)_(?P<measurement_date>\\d{8}).*$"
  default_side: "int"
  supplier_settings:
    file_prefix_side_map:
      I: int
      E: ext
```

Adapter `piece_folder_regex`, `folder_metadata_regex`, `geom_file_regex` au format réel.

#### Étape 5 — Configuration dans `config/suppliers_config.yaml`

Ajouter :

```yaml
  Mon Fournisseur:
    aliases: ["Mon Fournisseur", "MON_FOURNISSEUR", "MONFOURNISSEUR"]
    parser_class: "MonFournisseurParser"
    description: "Fournisseur XYZ (27 sections)"
```

#### Étape 6 — Tester

```bash
# Lister les configs
mle-heatmap --list-configs

# Exécuter sur un dossier de test
mle-heatmap --input-dir data/in/mon_fournisseur --part-number 362 --supplier "Mon Fournisseur" --output output
```

Créer des tests dans `tests/unit/test_parsers.py` ou un fichier dédié.

#### Résumé des fichiers à modifier

| Fichier | Action |
|---------|--------|
| `parsers/mon_fournisseur_parser.py` | Créer (ou adapter un parser existant) |
| `parsers/registry.py` | Ajouter `"MonFournisseurParser": MonFournisseurParser` |
| `config/parts_config.yaml` | Ajouter une entrée par part_number + supplier |
| `config/suppliers_config.yaml` | Ajouter le fournisseur avec aliases et parser_class |

---

## 6. Métriques calculées

| Métrique | Signification |
|----------|---------------|
| **widthness** | Largeur de la section (écart X max − min). |
| **tangent** | Pente tangentielle (ratio) de la section. |
| **chords** | Longueur de corde (distance entre points extrêmes). |
| **thickness_intrados** | Épaisseur côté intrados. |
| **thickness_extrados** | Épaisseur côté extrados. |
| **skeleton** | Centre de la section (moyenne des points). |

Les calculs avancés viennent du package `calcul_geom_descr_mle` s’il est installé ; sinon des formules de repli sont utilisées.

---

## 7. Configuration — Changer le comportement

### `config/parts_config.yaml`

Définit, pour chaque couple (part_number, supplier) :

- `sections_count` : nombre de sections attendues.
- `geom_folder_name` : nom du dossier GEOM (généralement `"GEOM"`).
- `geom_file_extensions` : extensions autorisées (`.mea`, `.xyz`, etc.).
- `geom_file_regex` : expression pour extraire section et préfixe (I/E) du nom de fichier.
- `folder_metadata_regex` : extraction du numéro de série, date, heure depuis le nom du dossier.
- `file_prefix_side_map` : I → int, E → ext (ou équivalents).
- **`z_to_cr_map`** : mapping optionnel `{ Z_value : CR_label }` pour associer une cote Z à un cercle de référence (CR). Utile pour le format .xyz où les sections sont déduites du Z.

Exemple `z_to_cr_map` dans `supplier_settings` :

```yaml
supplier_settings:
  z_to_cr_map:
    "281.1": "03"
    "285.2": "05"
    "290.0": "08"
  z_grouping_tolerance: 0.1   # tolérance (mm) pour matcher Z → CR
```

Si `z_to_cr_map` est défini, les points dont le Z est à l’intérieur de la tolérance sont assignés au CR correspondant. Sinon, le regroupement se fait automatiquement par Z.

### `config/suppliers_config.yaml`

- Aliases de fournisseurs (ex. TECT PA, TECT_PA, TECTPA).
- **parser_class** : nom du parser à utiliser (CZTParser, MLXParser, TECTParser, XYZFolderParser).
- Mapping des tokens de face (INT → int, EXT → ext).

### Variables d'environnement (`.env`)

- `OUTPUT_DIR` : dossier de sortie.
- `LOG_LEVEL` : niveau de log (INFO, DEBUG, etc.).
- `MLE_PROJECT_ROOT` : racine du projet (fallback si chemins incorrects).
- `MLE_CONFIG_DIR` : dossier des fichiers de configuration.

---

## 8. Évolution et maintenance

### Adapter le parsing à un nouveau fournisseur

1. **Analyser** la structure réelle des dossiers et fichiers du fournisseur.
2. **Vérifier** la convention : dossier pièce → GEOM → fichiers.
3. **Choisir** :
   - soit le comportement par défaut (un fichier par section, nommage I/E + numéro),
   - soit une surcharge de `_parse_geom_folder` pour une logique personnalisée (ex. deux .xyz, regroupement par Z).
4. **Tester** sur des données réelles (dossier de test).
5. **Documenter** le format dans ce fichier ou dans un README spécifique.

### Modifier une métrique ou un calcul

- Les calculs sont dans `processors/geometry_processor.py`.
- Le package externe `calcul_geom_descr_mle` fournit les fonctions principales.
- Les replis sont des approximations ; les ajuster si besoin.

### Ajouter une nouvelle métrique

1. Ajouter le type dans `MetricType` (`models/data_models.py`).
2. Implémenter la méthode de calcul dans `GeometryProcessor`.
3. Exposer l’option dans la CLI (`--metrics`).
4. Mettre à jour `parts_config.yaml` si la métrique dépend de la config.

### Tests et qualité

- Tests unitaires : `pytest` dans `tests/`.
- Formatage : `make format` (Black).
- Linting : `make lint` (Flake8).

### Déploiement

- `deploy.sh` : préparation de l’environnement (venv, dépendances, `.env`).
- `run_daily.sh` : exécution planifiée en batch (variables `DAILY_*`).

---

## Résumé des attentes

1. **Structure** : un dossier par pièce, contenant toujours un sous-dossier GEOM.
2. **Données** : points (X, Y, Z) avec section et face (int/ext).
3. **Parsing** : logique adaptable par fournisseur via `_parse_geom_folder`.
4. **Sortie** : CSV consolidé par pièce, prêt pour le pipeline heatmap.

Pour toute question ou évolution, se référer aux parsers existants (MLX, CZT, TECT) et à la configuration dans `config/`.
