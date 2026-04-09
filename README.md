# MLE Heatmap Wrapper

Wrapper Python pour orchestrer le parsing métrologie MLE, les calculs géométriques et l'export CSV pour le pipeline heatmap.

> **Documentation complète** : voir [DOCUMENTATION.md](DOCUMENTATION.md) pour la méthodologie, l'usage et la maintenance (public non-technique inclus). 

## Objectif 

Ce projet transforme des donnees de points GEOM (ASCII) en resultats metriques exploitables: 

- widthness 
- tangent 
- chords 
- thickness_extrados 
- thickness_intrados 
- skeleton 

Le workflow principal est **batch par dossier de pieces**: 

1. selection d un couple `part_number` + `supplier` 
2. lecture des dossiers pieces dans un dossier d entree 
3. parsing des fichiers ASCII dans `GEOM` 
4. validation des donnees (sections, sides, qualite) 
5. calcul des metriques 
6. export CSV consolide par piece 

## Architecture 

Le code est organise en modules: 

- `cli/`: interface ligne de commande 
- `core/`: config, logging, metrics execution, discovery de pieces 
- `models/`: dataclasses et objets de configuration 
- `parsers/`: parsing fournisseur (CZT, MLX, TECT PA) 
- `processors/`: calcul metriques 
- `validators/`: controles de coherence et qualite 
- `exporters/`: export CSV + metriques execution ## Structure d entree attendue 

Exemple: 

```text
 data/in/mlx/ 
 %%% 362_850_019_6F9_INT_PC_JE407542-N_05022026_034232_ARCHIVE/ 
    %%% GEOM/ 
        %%% I03.MEA 
        %%% I05.MEA 
        %%% ... 

``` 

- le nom du dossier piece est utilise pour extraire serial/date/heure 
- le contenu `GEOM` peut contenir `.mea`, `.txt`, `.dat`, `.asc`, `.csv` 
- les regles exactes viennent de `config/parts_config.yaml` 

## Installation 

```bash 
pip install -e . 
``` 

Pour developpement: 

```bash 
pip install -e ".[dev]" 
``` 

## Utilisation CLI 

### Lister les configurations disponibles 

```bash 
mle-heatmap --list-configs 
``` 

### Mode batch (recommande) 

```bash 
mle-heatmap \ --input-dir data/in/mlx \ --part-number 362 \ --supplier MLX \ --metrics widthness tangent \ --output output 
``` 

### Mode legacy fichier unique 

```bash 
mle-heatmap \ --input-file data/input.csv \ --part-number 362 \ --supplier CZT \ --output output 
``` 

## Convention de nommage des sorties Le CSV consolide piece suit la convention: 

```text 
<serial_number>_<supplier>_<partnumber>_<measurement_date>.csv 
``` 

Exemple: 
```text 
JE407542-N_MLX_362_20260205.csv 
``` 

## Configuration metier

### `config/parts_config.yaml` 

Definit par couple part/supplier: 

- nombre de sections attendu 
- regex dossier piece 
- regex fichiers GEOM 
- regles extraction metadata 
- contraintes validation (strict_section_count, require_both_sides) 

### `config/suppliers_config.yaml` 

Definit: 

- aliases fournisseur (ex: `TECT PA`, `TECT_PA`, `TECTPA`) 
- aides mapping token side ## Scripts utilitaires 
- `deploy.sh`: prepare environment local (venv, dependances, .env.example) 
- `run_daily.sh`: execution planifiee batch via variables `DAILY_*` 
- `usage_examples.py`: exemples programmatiques/CLI reproductibles 

## Developpement 

```bash 
make install-dev make test make format make lint 
``` 

## Ajouter un nouveau fournisseur ou part number 

1. ajouter la config dans `parts_config.yaml` 
2. si necessaire, ajouter alias/regles dans `suppliers_config.yaml` 
3. creer ou etendre parser dans `src/mle_heatmap_wrapper/parsers/` 
4. ajouter tests unitaires associes 

## Qualite et verification Avant livraison: 

1. lancer `python3 -m pytest -q` 
2. verifier un run batch reel sur un dossier de pieces 
3. controler les CSV et les fichiers metrics (`output/metrics`)
