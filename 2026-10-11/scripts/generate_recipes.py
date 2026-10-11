#!/usr/bin/env python3
"""Générateur de propositions de recettes à partir du catalogue du drive Le Drivé Tout Nu.

Pipeline :
  1. Charge le snapshot catalogue (data/catalogue/snapshot_<date>.json)
  2. Charge ou génère les recettes (data/recettes/recettes_<date>.json)
     -> si absent, lance agent_recettes_v2.py
  3. Matching recettes ↔ produits du catalogue (par ingrédients)
  4. Filtres :
     - pas de viande rouge (bœuf, veau, porc, poulet...)
     - poisson/ fruits de mer autorisés
     - bouillon cube/tablette/liquide OK
     - prix estimé ≤ 8 €/pers
     - temps total ≤ 45 min (cuisson), préparation ≤ 15 min
  5. Rend 3 propositions gourmandes avec prix estimé, mode opératoire, etc.

Usage :
  python3 generate_recipes.py                    # recettes du jour
  python3 generate_recipes.py --recents          # recettes récentes (moins de 7 jours)
  python3 generate_recipes.py --json             # sortie JSON brute
  python3 generate_recipes.py --refresh          # force régénération des recettes

Source :
  - data/catalogue/snapshot_<date>.json (généré par agent_catalogue.py)
  - data/recettes/recettes_<date>.json (généré par agent_recettes_v2.py)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent.parent

PARIS_TZ = timezone(timedelta(hours=2), "Europe/Paris")
date = datetime.now(PARIS_TZ).strftime('%Y-%m-%d')


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    return strip_accents(s.lower())


def latest_snapshot() -> Optional[Path]:
    files = sorted((BASE / "data" / "catalogue").glob("snapshot_*.json"))
    return files[-1] if files else None


def latest_recipes() -> Optional[Path]:
    files = sorted((BASE / "data" / "recettes").glob("recettes_*.json"))
    return files[-1] if files else None


def load_snap(snap_path: Path) -> dict:
    return json.loads(snap_path.read_text(encoding="utf-8"))


def load_recipes(recipes_path: Path) -> dict:
    return json.loads(recipes_path.read_text(encoding="utf-8"))


def parse_time_iso(s: str) -> int:
    """Parse ISO 8601 duration → minutes (ex: 'PT1H30M' → 90, 'PT45M' → 45)."""
    if not s:
        return 0
    s = s.upper()
    total = 0
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', s)
    if m:
        h, m = m.groups()
        if h:
            total += int(h) * 60
        if m:
            total += int(m)
    return total


def extract_base_ingredient(ing: str) -> str:
    """Extrait le nom de base d'un ingrédient (ex: "2 tomates fraîches" → "tomate")."""
    # Ignorer quantités/prefixes
    words = norm(ing).split()
    # Liste blanche des mots à conserver
    keepers = [
        "tomate", "courgette", "aubergine", "poireau", "carotte", "poivron",
        "pomme de terre", "pomme de terre", "pommes de terre", "salade",
        "concombre", "radis", "oignon", "oignons", "champignon", "champignons",
        "épinard", "épinards", "brocoli", "brocolis", "citrouille", "patate douce",
        "courge spaghetti", "courge", "butternut", "navet", "panais", "betterave",
        "haricot vert", "haricots verts", "maïs", "pois chiche", "lentille",
        "pomme", "poire", "citron", "orange", "fraise", "framboise", "myrtille",
        "abricot", "pêche", "kiwi", "ananas", "melon", "pastèque",
        "beurre", "huile", "sel", "poivre", "thym", "basilic", "origan",
        "persil", "ciboulette", "ail", "oignon", "échalote", "gingembre",
        "muscade", "curry", "paprika", "curcuma", "cumin", "coriandre",
        "laurier", "baie", "moulu", "fraîche", "frais", "séché", "sèche",
        "moyen", "moyenne", "grand", "grande", "petit", "petite", "fraîches",
        "frais", "frais", "surgelé", "surgelée", "congelé", "congelée",
    ]
    # Essayer de trouver un nom connu
    for kw in keepers:
        if kw in norm(ing):
            return kw
    # Fallback : premier nom >= 4 lettres
    for w in words:
        if len(w) >= 4 and w.isalpha():
            return w
    return norm(ing).split()[0] if words else ""


def build_ingredient_index(snap: dict) -> dict[str, list]:
    """Indexe les produits par nom de base (ex: 'tomate' → liste de tous les articles tomate)."""
    idx: dict[str, list] = {}
    for p in snap.get("products", []):
        title = p.get("title", "")
        base = extract_base_ingredient(title)
        if not base:
            continue
        if base not in idx:
            idx[base] = []
        idx[base].append(p)
    return idx


def is_restricted_ingredient(ing: str) -> bool:
    """Détecte si l'ingrédient contient une viande interdite.
    
    Vérifie les mots-complets (ex: 'poulet' mais pas 'oignon')
    pour éviter les faux positifs.
    Exception : 'bouillon de volaille' est autorisé.
    """
    n = norm(ing)
    # Interdits
    interdits = [
        "bœuf", "boeuf", "veau", "porc", "pork", "poulet", "volaille",
        "canard", "dinde", "oyat", "cheval", "chevaux",
        "andouillette", "andouille", "saucisse", "chorizo", "salami",
        "jambon", "bacon", "lard", "cotechino", "zampone", "rôtissage",
    ]
    interdits_norm = [norm(i) for i in interdits]
    words = n.split()
    # Vérifier mots-complets uniquement
    for w in words:
        if w in interdits_norm:
            # Exception : 'bouillon de volaille' est autorisé
            if w == "volaille" and "bouillon" in n:
                continue
            return True
    return False


def is_allowed_fish_or_seafood(ing: str) -> bool:
    """Détecte si l'ingrédient est poisson ou fruit de mer (autorisé)."""
    n = norm(ing)
    poissons = [
        "saumon", "thon", "colin", "cabillaud", "merlu", "bars", "bar",
        "truite", "perche", "flétan", "sardine", "maquereau", "merlan",
        "colin", "saumon", "tacaud", "lotte", "tourteau", "homard",
        "crabe", "églefin", "araignée", "crevette", "crevettes",
        "langoustine", "langoustines", "moule", "moules", "mollusque",
        "calmar", "calmars", "poulpe", "crevette", "grisbi", "gomphotherium",
    ]
    return any(p in n for p in poissons)


def is_allowed_bouillon(ing: str) -> bool:
    """Détecte si le bouillon est autorisé (cube/tablette/liquide, toute espèce)."""
    n = norm(ing)
    bouillons = ["bouillon", "fond", "cube", "tablette", "liquide", "déshydraté"]
    return any(b in n for b in bouillons)


def filter_recipe(recipe: dict, snap: dict) -> tuple[bool, str]:
    """Filtre une recette selon les règles familiales. Retourne (ok, reason).
    
    Ordre des tests IMPORTANT : bouillon d'abord (volaille OK), puis viande, puis poisson.
    """
    ingredients = recipe.get("ingredients", [])
    if not ingredients:
        return False, "pas d'ingrédients"

    # Regarder chaque ingrédient
    for ing in ingredients:
        # 1. Bouillon → OK (toute espèce, y compris volaille)
        if is_allowed_bouillon(ing):
            continue
        # 2. Poisson/fruit de mer → OK
        if is_allowed_fish_or_seafood(ing):
            continue
        # 3. Viande interdite → REJET
        if is_restricted_ingredient(ing):
            return False, f"viande interdite : {ing}"
    return True, ""


def estimate_price(recipe: dict, idx: dict[str, list]) -> float:
    """Estime le prix total de la recette (somme des ingrédients trouvés)."""
    total = 0.0
    for ing in recipe.get("ingredients", []):
        base = extract_base_ingredient(ing)
        candidates = idx.get(base, [])
        if candidates:
            # Prend le moins cher
            prices = [p.get("price_eur") for p in candidates if p.get("price_eur")]
            if prices:
                total += min(prices)
    return total


def estimate_servings(recipe: dict) -> int:
    """Estime le nombre de personnes (par défaut 4, ou extrait de yield)."""
    yield_ = recipe.get("yield", "")
    if not yield_:
        return 4
    m = re.search(r"(\d+)\s*(personnes?|pers)", yield_)
    if m:
        return int(m.group(1))
    return 4


def estimate_times(recipe: dict) -> tuple[int, int, int]:
    """Retourne (prep, cook, total) en minutes."""
    prep = parse_time_iso(recipe.get("time_prep", ""))
    cook = parse_time_iso(recipe.get("time_cook", ""))
    total = parse_time_iso(recipe.get("time_total", ""))
    if not total and prep and cook:
        total = prep + cook
    if not prep and total and cook:
        prep = max(0, total - cook)
    if not cook and total and prep:
        cook = max(0, total - prep)
    return prep, cook, total or (prep + cook)


def format_steps(steps: list) -> str:
    """Formate les étapes de cuisson."""
    if isinstance(steps, int):
        return f"{steps} étapes"
    return "; ".join(str(s) for s in steps)[:120]


def is_dessert(title: str) -> bool:
    """Détecte si la recette est un dessert (exclut les tartes salées).
    
    Exclut explicitement :
    - gateau/muffin/brioche/flan/financier/mousse/soufflé/pannacotta
    - tarte + sucré (prune, abricot, cerise, framboise, etc.)
    - salade de fruits
    
    Inclut (exceptions) :
    - salade + légumes (ex: salade de courgettes)
    - tarte + légumes (ex: tarte aux lardons/courgettes)
    """
    t = norm(title)
    
    # Mots-clés qui excluent certainement un dessert
    dessert_definitive = [
        'gateau', 'gâteau', 'muffin', 'financier', 'brioche', 'flan',
        'mousse', 'soufflé', 'pannacotta', 'confit', 'compote', 'abricot',
        'cerise', 'fraise', 'framboise', 'mûre', 'myrtille', 'pêche',
        'pomme sucrée', 'poire sucrée', 'orange confite', 'citron confit',
        'tarte sucrée', 'tarte aux fruits', 'tarte aux pommes', 'tarte aux poires',
    ]
    for kw in dessert_definitive:
        if kw in t:
            return True
    
    # Gestion des tartes : 'tarte' + mot sucré = dessert
    if 'tarte' in t:
        sweet_fruits = ['prune', 'abricot', 'cerise', 'fraise', 'framboise', 'mûre',
                        'myrtille', 'pêche', 'pomme', 'poire', 'noix', 'noisette',
                        'châtaigne', 'chocolat', 'caramel', 'creme', 'crème',
                        'confiture', 'miel', 'miel', 'sucre', 'sucrée']
        for kw in sweet_fruits:
            if kw in t:
                return True
        # Exception : 'tarte' + légumes/salé
        savory = ['courgette', 'tomate', 'poireau', 'lardon', 'jambon', 'fromage',
                  'epinard', 'épinard', 'champignon', 'poisson', 'thon', 'saumon']
        if any(l in t for l in savory):
            return False
        return True
    
    # Gestion des salades : 'salade' + fruit = dessert, 'salade' + legume = plat
    if 'salade' in t:
        fruits = ['fruit', 'orange', 'mandarine', ' grenade', 'grenade', 'pomme',
                  'pêche', 'abricot', 'cerise', 'fraise', 'framboise', 'mûre',
                  'myrtille', 'pomme', 'poire', 'melon', 'pastèque']
        for kw in fruits:
            if kw in t:
                return True
        # Salade + légume OK (plat principal)
        legumes = ['courgette', 'tomate', 'poireau', 'carotte', 'betterave',
                   'concombre', 'radis', 'céleri', 'haricot', 'lentille', 'pomme de terre']
        if any(l in t for l in legumes):
            return False
    
    return False


def propose_recipes(snap: dict, recipes_data: dict, max_results: int = 3) -> list[dict]:
    """Génère les propositions de recettes.
    
    Filtre :
    - pas de desserts
    - pas de viande rouge
    - poisson/fruit de mer OK
    - bouillon cube/tablette OK
    - prix ≤ 8 €/pers
    - temps ≤ 60 min (total)
    """
    idx = build_ingredient_index(snap)
    candidates = []
    for r in recipes_data.get("recipes", []):
        ok, reason = filter_recipe(r, snap)
        if not ok:
            continue
        prep, cook, total = estimate_times(r)
        if total > 60:
            continue
        if prep > 15:
            continue
        prix_total = estimate_price(r, idx)
        pers = estimate_servings(r)
        if pers == 0:
            pers = 4
        prix_pers = prix_total / pers
        if prix_pers > 8.0:
            continue
        # Exclure les desserts
        if is_dessert(r.get('title', '')):
            continue
        candidates.append({
            "title": r.get("title", "Sans titre"),
            "url": r.get("url", ""),
            "ingredients": r.get("ingredients", []),
            "est_total": round(prix_total, 2),
            "est_pers": round(prix_pers, 2),
            "prep_min": prep,
            "cook_min": cook,
            "total_min": total,
            "steps": format_steps(r.get("steps", 0)),
            "yield": r.get("yield", ""),
            "image": r.get("image", ""),
        })
    # Trie par prix croissant, puis par temps total croissant
    candidates.sort(key=lambda x: (x["est_pers"], x["total_min"]))
    return candidates[:max_results]


def main() -> int:
    parser = argparse.ArgumentParser(description="Propositions de recettes Le Drivé Tout Nu")
    parser.add_argument("--recents", action="store_true", help="recettes récentes (moins de 7 jours)")
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    parser.add_argument("--refresh", action="store_true", help="force régénération des recettes")
    args = parser.parse_args()

    # 1. Charger le catalogue
    snap_path = latest_snapshot()
    if not snap_path:
        print("Aucun catalogue trouvé — lancez agent_catalogue.py", file=sys.stderr)
        return 1
    snap = load_snap(snap_path)

    # 2. Charger ou générer les recettes
    recipes_path = latest_recipes()
    need_refresh = args.refresh or not recipes_path
    if need_refresh:
        # Exécuter agent_recettes_llm_v2.py (LLM), fallback Marmiton si échec
        import subprocess
        result = subprocess.run(
            [sys.executable, str(BASE / "agents" / "agent_recettes_llm_v2.py"), "--count", "20"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Fallback Marmiton si LLM échoue
            print(f"[generate_recipes] ⚠️ LLM échoué, fallback Marmiton...")
            result = subprocess.run(
                [sys.executable, str(BASE / "agents" / "agent_recettes_v2.py")],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"Erreur collecte recettes : {result.stderr}", file=sys.stderr)
                return 1
        recipes_path = latest_recipes()
        if not recipes_path:
            print("Échec collecte recettes (aucun fichier généré)", file=sys.stderr)
            return 1

    recipes_data = load_recipes(recipes_path)

    # Filtrer date (si --recents)
    today = datetime.now(PARIS_TZ).date()
    recipes_date = datetime.fromisoformat(recipes_data.get("date", today.isoformat())).date()
    if args.recents and (today - recipes_date).days > 7:
        print("Aucune recette récente trouvée", file=sys.stderr)
        return 1

    # 3. Proposer
    proposals = propose_recipes(snap, recipes_data, max_results=3)

    # Sauvegarder propositions (pour le pipeline)
    props_path = BASE / 'data' / 'propositions' / f'propositions_{date}.json'
    props_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "catalogue": snap_path.name,
        "recettes": recipes_path.name,
        "propositions": proposals,
        "timestamp": datetime.now(PARIS_TZ).isoformat(),
    }
    props_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Propositions sauvegardées : {props_path.name}")

    # Sortie
    if args.json:
        output = {
            "catalogue": snap_path.name,
            "recettes": recipes_path.name,
            "recipes": proposals,
            "timestamp": datetime.now(PARIS_TZ).isoformat(),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    # Format lisible
    print(f"Propositions de recettes — {len(proposals)} idées")
    print(f"Catalogue : {snap_path.name} ({snap.get('count', '?')} produits)")
    print(f"Recettes : {recipes_path.name} ({recipes_data.get('count', '?')} recettes)")
    print()

    for i, r in enumerate(proposals, 1):
        print(f"#{i} {r['title']}")
        print(f"   URL : {r['url']}")
        print(f"   Estimation : {r['est_pers']:.2f} €/pers (total {r['est_total']:.2f} €)")
        print(f"   Temps : prépa {r['prep_min']} min, cuisson {r['cook_min']} min (total {r['total_min']} min)")
        print(f"   Étapes : {r['steps']}")
        print()

    return 0 if proposals else 1


if __name__ == "__main__":
    raise SystemExit(main())
