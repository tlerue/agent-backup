#!/usr/bin/env python3
"""Agent 3 (LLM) v2 — Recettes : génération créative depuis le catalogue drive.

Remplace la collecte Marmiton par un LLM (dots-studii / Open WebUI) piloté
par un prompt engineering structuré.

Conformité :
  - Entrée : snapshot catalogue du jour (data/catalogue/snapshot_<date>.json)
  - Sortie : data/recettes/recettes_<date>.json  (format compatible agent_matching.py)
  - Contraintes familiales appliquées en amont (prompt) + en aval (filtre)
  - Pas de scraping : appel API JSON uniquement
  - Budget tokens contrôlé : 512k max, ~2k prompt + ~1k/récipe

Configuration env :
  LLM_API_URL   - endpoint Open WebUI / compatible (défaut: http://localhost:8080/api/generate)
  LLM_MODEL     - nom du modèle (défaut: dots-studii)
  LLM_TIMEOUT   - timeout secondes (défaut: 120)

Usage :
  python3 agents/agent_recettes_llm_v2.py
  python3 agents/agent_recettes_llm_v2.py --count 6 --out data/recettes/recettes_<date>.json
  python3 agents/agent_recettes_llm_v2.py --fallback-marmiton  --count 3
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

PARIS_TZ = timezone(timedelta(hours=2), "Europe/Paris")

BASE = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE / "agents" / "prompts" / "recette_creative_v2.txt"
MARMITON_AGENT = BASE / "agents" / "agent_recettes_v2.py"

# --- Configurable via env ---
# OpenRouter configuration (OpenAI-compatible)
API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
MODEL = os.getenv("LLM_MODEL", "qwen/qwen3-coder-next")
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# Read OpenRouter API key from env or file
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
if not OPENROUTER_API_KEY:
    home_key = Path.home() / ".openrouter_api_key"
    if home_key.exists():
        OPENROUTER_API_KEY = home_key.read_text().strip()

# Budget tokens pour l'API OpenRouter (1M tokens = ~10 recettes détaillées)
MAX_TOKENS_ESTIMATE = 1_024_000
TOKEN_OVERHEAD_PROMPT = 2_500
TOKEN_PER_RECIPE_ESTIMATE = 1_500


def pipeline_date() -> str:
    """Date du pipeline : aujourd'hui (ou override via env)."""
    return datetime.now(PARIS_TZ).strftime("%Y-%m-%d")


def latest_snapshot_path() -> Path:
    """Retourne le chemin du dernier snapshot disponible (pas de forcer la date)."""
    files = sorted((BASE / "data" / "catalogue").glob("snapshot_*.json"))
    if not files:
        raise FileNotFoundError("Aucun snapshot catalogue disponible")
    return files[-1]


def snapshot_date(snap_path: Path) -> str:
    """Extrait la date du snapshot (depuis le JSON ou le nom de fichier)."""
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        if "date" in snap:
            return snap["date"]
    except Exception:
        pass
    m = re.search(r"snapshot_(\d{4}-\d{2}-\d{2})", snap_path.name)
    if m:
        return m.group(1)
    return pipeline_date()


# ---------------------------------------------------------------------------
# Load prompt template
# ---------------------------------------------------------------------------
def load_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt introuvable : {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Extract catalogue ingredients (fruits + légumes + bases)
# ---------------------------------------------------------------------------
def ingredients_from_snapshot(snap_path: Path) -> list[dict]:
    """Extrait les produits du catalogue pour les ancres de recettes."""
    if not snap_path.exists():
        return []
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    out = []
    for p in snap.get("products", []):
        t = p.get("type", "")
        if t in ("Fruits", "Légumes", "Autre"):
            out.append({
                "title": p["title"],
                "type": t,
                "price_eur": p.get("price_eur", 0),
                "available": p.get("available", True),
            })
    return out


# ---------------------------------------------------------------------------
# Build the prompt with actual catalogue data
# ---------------------------------------------------------------------------
def build_prompt(ingredients: list[dict], count: int = 6) -> str:
    template = load_prompt()
    catalogue_json = json.dumps({
        "date": pipeline_date(),
        "ingredients": ingredients,
        "count": count,
    }, ensure_ascii=False, indent=2)
    # Inject catalogue JSON into prompt after the INPUT FORMAT marker
    marker = "## Entrée (JSON reçu du pipeline)"
    if marker in template:
        parts = template.split(marker, 1)
        return parts[0] + marker + "\n" + catalogue_json + "\n" + parts[1]
    return template + "\n\n" + catalogue_json


# ---------------------------------------------------------------------------
# Call LLM API (OpenRouter OpenAI-compatible)
# ---------------------------------------------------------------------------
def call_llm(prompt: str) -> str:
    """Appel API OpenRouter → retourne le texte brut de la réponse."""
    # OpenRouter uses OpenAI-compatible chat completions format
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Tu es un expert en cuisine française. Rédige des recettes simples, accessibles, respectant les contraintes alimentaires (pas de viande, poisson autorisé, bouillons cube/tablette/liquide OK)."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/tlerue/ntfy-md-notif",
        "X-Title": "courses-recettes",
    }

    req = urllib.request.Request(API_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
        
        # OpenAI-compatible response format
        data = json.loads(raw)
        
        # Extract content from chat completions response
        if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
            message = data["choices"][0].get("message", {})
            return message.get("content", "")
        
        raise RuntimeError(f"Format réponse OpenRouter inattendu : {list(data.keys())}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if hasattr(e, 'read') else ""
        raise RuntimeError(f"API OpenRouter HTTP {e.code} : {e.reason} - {error_body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"API OpenRouter injoignable : {e.reason}") from e


# ---------------------------------------------------------------------------
# Parse LLM response → structured recipes
# ---------------------------------------------------------------------------
def extract_json(text: str) -> list[dict]:
    """Extrait le premier JSON valide dans le texte de réponse."""
    # Enlever les backticks markdown si présents
    if text.strip().startswith("```json"):
        text = text.strip()[7:]  # Enlever ```json
    if text.strip().endswith("```"):
        text = text.strip()[:-3]  # Enlever ```
    text = text.strip()
    
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        parsed = json.loads(candidate)
                        return parsed if isinstance(parsed, list) else [parsed]
                    except json.JSONDecodeError:
                        continue
    raise ValueError("Aucun JSON valide trouvé dans la réponse LLM")


# ---------------------------------------------------------------------------
# Normalize LLM recipe → Marmiton-compatible schema + filter desserts
# ---------------------------------------------------------------------------
ISO8601_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def is_dessert_recipe(title: str, ingredients_all: list) -> bool:
    """Détecte si la recette est un dessert (exclut les tartes salées)."""
    t = title.lower()
    
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
    
    # Gestion des tartes
    if 'tarte' in t:
        sweet_fruits = ['prune', 'abricot', 'cerise', 'fraise', 'framboise', 'mûre',
                        'myrtille', 'pêche', 'pomme', 'poire', 'noix', 'noisette',
                        'châtaigne', 'chocolat', 'caramel', 'creme', 'crème',
                        'confiture', 'miel', 'sucre', 'sucrée']
        for kw in sweet_fruits:
            if kw in t:
                return True
        savory = ['courgette', 'tomate', 'poireau', 'lardon', 'jambon', 'fromage',
                  'epinard', 'champignon', 'poisson', 'thon', 'saumon']
        if any(l in t for l in savory):
            return False
        return True
    
    # Gestion des salades
    if 'salade' in t:
        fruits = ['fruit', 'orange', 'mandarine', ' grenade', 'grenade', 'pomme',
                  'pêche', 'abricot', 'cerise', 'fraise', 'framboise', 'mûre',
                  'myrtille', 'pomme', 'poire', 'melon', 'pastèque']
        for kw in fruits:
            if kw in t:
                return True
        legumes = ['courgette', 'tomate', 'poireau', 'carotte', 'betterave',
                   'concombre', 'radis', 'céleri', 'haricot', 'lentille', 'pomme de terre']
        if any(l in t for l in legumes):
            return False
    
    # Vérifier ingrédients_all
    for ing in ingredients_all:
        if isinstance(ing, str):
            it = ing.lower()
        elif isinstance(ing, dict):
            it = (ing.get("name", "") or "").lower()
        else:
            it = str(ing).lower()
        if any(kw in it for kw in ['sucrée', 'confiture', 'miel', 'creme', 'crème']):
            # Exception : crème = ingrédient plat (ex: soupe crémeuse)
            if any(kw in t for kw in ['soupe', 'velouté', 'gratin', 'flan']):
                continue
            if any(kw in t for kw in ['gateau', 'muffin', 'tarte']):
                return True
    
    return False


def normalize_recipe(raw: dict, anchor: str, index: int) -> dict | None:
    """Valide et normalise une recette LLM vers le schema Marmiton + filtre desserts."""
    # Validation obligatoire
    title = (raw.get("title") or "").strip()
    if not title:
        return None

    ingredients_all = raw.get("ingredients_all") or raw.get("ingredients") or []
    if not isinstance(ingredients_all, list):
        return None

    # Contrainte familiale : aucun ingrédient ne doit contenir de viande
    meat_words = [
        "boeuf", "veau", "porc", "poulet", "agneau", "jambon", "lardon",
        "bacon", "saucisse", "saucisson", "chorizo", "steak", "roti",
        "escalope", "cotelette", "carbonnade", "daube", "navarin", "blanquette",
        "pot-au-feu", "jarret", "filet mignon", "paupiette", "confit",
        "bolognaise", "carbonara", "cassoulet", "terrine", "haché",
    ]
    for ing in ingredients_all:
        name = ing if isinstance(ing, str) else ing.get("name", "")
        name_low = name.lower()
        for mw in meat_words:
            if mw in name_low:
                return None  # recette non conforme → écartée

    prep_min = int(raw.get("prep_min") or 0)
    cook_min = int(raw.get("cook_min") or 0)
    if prep_min > 15 or cook_min < 30 or cook_min > 45:
        return None  # hors budget temps

    # **NOUVEAU Filtre desserts**
    if is_dessert_recipe(title, ingredients_all):
        return None  # recette dessert → écartée

    # Construire les ingrédients au format texte libre (compatible matching)
    ingredients_text = []
    for ing in ingredients_all:
        if isinstance(ing, str):
            ingredients_text.append(ing)
        else:
            qty = ing.get("qty", "")
            unit = ing.get("unit", "")
            name = ing.get("name", "")
            ingredients_text.append(f"{qty} {unit} {name}".strip())

    # Steps
    steps = raw.get("steps") or []

    # ISO 8601 durations
    time_prep = f"PT{prep_min}M" if prep_min else "PT15M"
    time_cook = f"PT{cook_min}M" if cook_min else "PT35M"
    total_min = prep_min + cook_min
    time_total = f"PT{total_min}M"

    # Creativity tag
    creativity = raw.get("creativity_tag", "inventé")
    if creativity not in ("fusion", "réinventé", "inventé", "classique_amélioré"):
        creativity = "inventé"

    # Dish type
    dish_type = raw.get("dish_type", "plat")
    if dish_type not in ("plat", "soupe", "gratin", "bowls", "accompagnement"):
        dish_type = "plat"

    # Tools
    tools = raw.get("tools", ["magimix", "four"])
    if not isinstance(tools, list):
        tools = ["magimix", "four"]

    return {
        "title": title,
        "url": f"https://llm-generated.recipes/{pipeline_date()}/{index:02d}-{re.sub(r'[^a-z0-9]+', '-', title.lower())[:40]}",
        "ingredients": ingredients_text,
        "steps": len(steps),
        "time_total": time_total,
        "time_prep": time_prep,
        "time_cook": time_cook,
        "yield": "4 personnes",
        "image": None,
        "anchor": anchor,
        "source": "llm",
        "creativity_tag": creativity,
        "description": raw.get("description", ""),
        "dish_type": dish_type,
        "tools": tools,
        "family_ok": True,
    }


# ---------------------------------------------------------------------------
# Fallback Marmiton
# ---------------------------------------------------------------------------
def fallback_marmiton(count: int) -> dict:
    """Appele agent_recettes_v2.py en fallback si LLM échoue."""
    import subprocess
    # Pas d'affichage ici : main() s'en charge pour éviter les doublons
    result = subprocess.run(
        [sys.executable, str(MARMITON_AGENT)],
        capture_output=True,
        text=True,
        env={**os.environ, "LLM_MODE": "fallback"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Échec Marmiton fallback : {result.stderr}")
    # Parse JSON de la sortie
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        # Fallback : chercher fichier récent
        date = pipeline_date()
        path = BASE / "data" / "recettes" / f"recettes_{date}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise RuntimeError("Aucune sortie Marmiton disponible")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Agent recettes LLM v2 — génération créative + fallback Marmiton")
    parser.add_argument("--count", type=int, default=6, help="nombre de recettes à générer")
    parser.add_argument("--out", type=str, default=None, help="chemin sortie (défaut: data/recettes/recettes_<date>.json)")
    parser.add_argument("--prompt-only", action="store_true", help="afficher le prompt construit sans appel LLM")
    parser.add_argument("--dry-run", action="store_true", help="afficher le résumé sans appel LLM")
    parser.add_argument("--fallback-marmiton", action="store_true", help="activer le fallback Marmiton si LLM échoue")
    args = parser.parse_args()

    # Utiliser le dernier snapshot disponible (pas de forcer la date)
    try:
        snap_path = latest_snapshot_path()
    except FileNotFoundError as e:
        print(f"[recettes-llm-v2] ❌ {e}", file=sys.stderr)
        return 1

    date = snapshot_date(snap_path)
    ingredients = ingredients_from_snapshot(snap_path)
    if not ingredients:
        print(f"[recettes-llm-v2] ❌ Catalogue vide : {snap_path}", file=sys.stderr)
        return 1

    print(f"[recettes-llm-v2] {len(ingredients)} ingrédients catalogue ({date})")
    print(f"[recettes-llm-v2] Snapshot : {snap_path.name}")
    print(f"[recettes-llm-v2] Modèle : {MODEL} | API : {API_URL}")

    # Token budget check
    estimated_tokens = TOKEN_OVERHEAD_PROMPT + args.count * TOKEN_PER_RECIPE_ESTIMATE
    if estimated_tokens > MAX_TOKENS_ESTIMATE:
        print(f"[recettes-llm-v2] ⚠ Budget tokens dépassé ({estimated_tokens} > {MAX_TOKENS_ESTIMATE}) — réduire --count", file=sys.stderr)
        return 1

    prompt = build_prompt(ingredients, count=args.count)

    if args.prompt_only:
        print(prompt)
        return 0

    if args.dry_run:
        print(f"[recettes-llm-v2] Dry-run : {args.count} recettes, ~{estimated_tokens} tokens estimés")
        print(f"[recettes-llm-v2] Ingrédients : {', '.join(i['title'] for i in ingredients[:10])}...")
        return 0

    # Call LLM
    print(f"[recettes-llm-v2] Appel LLM ({MODEL})...")
    t0 = time.monotonic()
    try:
        response = call_llm(prompt)
    except RuntimeError as e:
        print(f"[recettes-llm-v2] ❌ Erreur LLM : {e}", file=sys.stderr)
        print(f"[recettes-llm-v2] ⚠️ Échec LLM → fallback Marmiton ({args.count} recettes)")
        # Ne pas relancer fallback si déjà tenté (via args.fallback_marmiton)
        try:
            result = fallback_marmiton(count=args.count)
            # Sauvegarder dans le même format
            out_path = BASE / "data" / "recettes" / f"recettes_{date}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[recettes-llm-v2] → Fallback Marmiton ok : {out_path.name}")
            return 0 if result.get("count", 0) > 0 else 1
        except Exception as e2:
            print(f"[recettes-llm-v2] ❌ Échec fallback Marmiton : {e2}", file=sys.stderr)
            return 1
    elapsed = round(time.monotonic() - t0, 1)
    print(f"[recettes-llm-v2] Réponse reçue en {elapsed}s ({len(response)} chars)")

    # Parse JSON
    try:
        raw_recipes = extract_json(response)
    except ValueError as e:
        print(f"[recettes-llm-v2] ❌ Parse JSON échoué : {e}", file=sys.stderr)
        debug_path = BASE / "data" / "recettes" / f"debug_{date}.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(response, encoding="utf-8")
        print(f"[recettes-llm-v2] Response brute sauvée : {debug_path}", file=sys.stderr)
        if args.fallback_marmiton:
            try:
                result = fallback_marmiton(count=args.count)
                out_path = BASE / "data" / "recettes" / f"recettes_{date}.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[recettes-llm-v2] → Fallback Marmiton ok : {out_path.name}")
                return 0 if result.get("count", 0) > 0 else 1
            except Exception as e2:
                print(f"[recettes-llm-v2] ❌ Échec fallback Marmiton : {e2}", file=sys.stderr)
                return 1
        return 1

    print(f"[recettes-llm-v2] {len(raw_recipes)} recettes brutes reçues")

    # Normalize + filter
    recipes = []
    rejected = 0
    for i, raw in enumerate(raw_recipes):
        rec = normalize_recipe(raw, anchor=ingredients[0]["title"] if ingredients else "catalogue", index=i)
        if rec:
            recipes.append(rec)
        else:
            rejected += 1

    print(f"[recettes-llm-v2] {len(recipes)} recettes conservées, {rejected} rejetées (contraintes)")

    # Renumber recipes with sequential index after filtering
    for idx, rec in enumerate(recipes):
        # Update URL with sequential index
        import re
        title_lower = rec['title'].lower()
        safe_title = re.sub(r'[^a-z0-9]+', '-', title_lower)[:40]
        date_part = rec['url'].split('/')[-2]  # Extract date from URL
        rec['url'] = f"https://llm-generated.recipes/{date_part}/{idx:02d}-{safe_title}"

    # Output
    out = {
        "date": date,
        "source": "llm",
        "model": MODEL,
        "count": len(recipes),
        "recipes": recipes,
        "prompt_tokens_estimate": estimated_tokens,
        "api_elapsed_s": elapsed,
    }
    out_path = Path(args.out) if args.out else BASE / "data" / "recettes" / f"recettes_{date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Log
    log_path = BASE / "logs" / f"recettes_{date}.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = [
        f"# Recettes {date}",
        "",
        f"## Source : LLM ({MODEL})",
        f"- Prompt : {PROMPT_PATH}",
        f"- Appel : {API_URL}",
        f"- Durée API : {elapsed}s",
        f"- Recettes brutes : {len(raw_recipes)}",
        f"- Recettes conservées : {len(recipes)}",
        f"- Rejetées (contraintes) : {rejected}",
        f"- Budget tokens estimé : {estimated_tokens} / {MAX_TOKENS_ESTIMATE}",
        "",
    ]
    for r in recipes:
        log.append(f"- {r['title'][:70]} (prep {r['time_prep']}, cook {r['time_cook']}, tag={r.get('creativity_tag','?')})")
    log_path.write_text("\n".join(log), encoding="utf-8")

    print(f"[recettes-llm-v2] → {out_path.name}  ({len(recipes)} recettes, log: {log_path.name})")
    for r in recipes:
        print(f"  ✓ {r['title'][:60]}  [{r.get('creativity_tag','?')}]  prep={r['time_prep']} cook={r['time_cook']}")
    
    # Générer les fichiers Markdown et les envoyer via ntfy-send-url.sh
    send_llm_recipes_to_ntfy(recipes, date)
    
    return 0 if recipes else 1


def generate_recipe_markdown(recipe: dict) -> str:
    """Génère le contenu Markdown d'une recette LLM."""
    lines = [
        f"# {recipe['title']}",
        "",
        f"**Source** : LLM ({MODEL}) | **Date** : {pipeline_date()}",
        "",
        f"**Tag créativité** : {recipe.get('creativity_tag', '?')}",
        f"**Type de plat** : {recipe.get('dish_type', '?')}",
        "",
        f"**Temps** : prépa **{int(recipe.get('time_prep','PT15M').replace('PT','').replace('M',''))} min**, cuisson **{int(recipe.get('time_cook','PT35M').replace('PT','').replace('M',''))} min**",
        "",
        f"**Description** : {recipe.get('description', 'Pas de description')}",
        "",
        "## Ingrédients",
        "",
    ]
    for ing in recipe.get('ingredients', []):
        lines.append(f"- {ing}")
    
    lines.extend([
        "",
        "## Préparation",
        "",
    ])
    steps = recipe.get('steps', 0)
    if isinstance(steps, list):
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
    else:
        lines.append(f"{steps} étapes (détails non fournis)")
    
    lines.extend([
        "",
        f"**Outils** : {', '.join(recipe.get('tools', ['magimix', 'four']))}",
        "",
        "---",
        f"*Recette générée automatiquement par l'agent LLM v2* | 📅 {pipeline_date()}",
    ])
    
    return "\n".join(lines)


def send_llm_recipes_to_ntfy(recipes: list, date: str) -> None:
    """Envoie chaque recette LLM via ntfy-send-url.sh."""
    import subprocess
    
    ntfy_script = Path("/home/user/.agents/skills/ntfy-send-url/ntfy-send-url.sh")
    
    if not ntfy_script.exists():
        print(f"[recettes-llm-v2] ❌ Script ntfy-send-url.sh introuvable : {ntfy_script}", file=sys.stderr)
        return
    
    # S'assurer que le répertoire de sortie existe
    out_dir = BASE / "data" / "recettes" / "llm"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Topic ntfy.sh
    TOPIC = "menez-roch-veur-en-bzh-que-c-est"
    
    for i, rec in enumerate(recipes):
        # Générer le contenu Markdown
        md_content = generate_recipe_markdown(rec)
        
        # Nom de fichier : recette_00-titre.md
        safe_title = re.sub(r'[^a-z0-9]+', '-', rec['title'].lower())[:50]
        filename = f"recette_{i:02d}-{safe_title}.md"
        md_path = out_dir / filename
        
        # Écrire le fichier .md
        md_path.write_text(md_content, encoding="utf-8")
        print(f"[recettes-llm-v2] ✍️ Fichier Markdown généré : {md_path.name}")
        
        # Appeler le script ntfy-send-url.sh
        print(f"[recettes-llm-v2] 📨 Envoi via ntfy-send-url.sh...")
        try:
            result = subprocess.run(
                [str(ntfy_script), str(md_path), TOPIC, f"Recette du jour : {rec['title']}"],
                cwd=BASE,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                print(f"[recettes-llm-v2] ✅ Recette envoyée (ntfy.sh + GitHub)")
                # Afficher l'URL viewer si disponible dans la sortie
                for line in result.stdout.split("\n"):
                    if "URL du viewer" in line:
                        print(f"[recettes-llm-v2]     {line.strip()}")
            else:
                print(f"[recettes-llm-v2] ❌ Erreur ntfy-send-url.sh : {result.stderr[:500]}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"[recettes-llm-v2] ❌ Timeout ntfy-send-url.sh", file=sys.stderr)
        except Exception as e:
            print(f"[recettes-llm-v2] ❌ ntfy error: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
