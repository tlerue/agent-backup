#!/usr/bin/env python3
"""Pipeline quotidien complet — Recettes Le Drivé Tout Nu.

Lance successivement :
1. agent_catalogue.py (si pas de snapshot du jour)
2. agent_recettes_llm_v2.py (génération LLM + fallback Marmiton)
3. cli/generate_recipes.py (matching + filtres + propositions)
4. cli/generate_report.py (rapport Markdown quotidien)

Sortie :
- data/catalogue/snapshot_<date>.json
- data/recettes/recettes_<date>.json
- data/recettes/propositions_<date>.json
- data/reports/recettes_<date>.md
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

PARIS_TZ = timezone(timedelta(hours=2), "Europe/Paris")
BASE = Path(__file__).resolve().parent.parent  # /home/user/courses-recettes

TOPIC = "menez-roch-veur-en-bzh-que-c-est"

# Script ntfy-send-url pour les notifications avec URL viewer
def send_ntfy_with_viewer(report_path: Path) -> None:
    """Envoie une notification via ntfy-send-url.sh avec URL viewer GitHub raw.
    
    Le script ntfy-send-url.sh gère automatiquement :
    - Le commit/push du fichier .md sur GitHub
    - La génération de l'URL viewer
    - L'envoi de la notification ntfy.sh avec Click action
    
    Topic : menez-roch-veur-en-bzh-que-c-est
    Texte : recette du drive tout nu
    """
    ntfy_script = Path("/home/user/.agents/skills/ntfy-send-url/ntfy-send-url.sh")
    
    if not ntfy_script.exists():
        print(f"[pipeline] ❌ Script ntfy-send-url.sh introuvable : {ntfy_script}", file=sys.stderr)
        return
    
    # Appeler le script ntfy-send-url.sh avec les bons paramètres
    print(f"[pipeline] 📨 Envoi de la notification via ntfy-send-url.sh...")
    print(f"[pipeline]     Rapport : {report_path}")
    print(f"[pipeline]     Topic : {TOPIC}")
    print(f"[pipeline]     Message : recette du drive tout nu")
    
    try:
        result = subprocess.run(
            [str(ntfy_script), str(report_path), TOPIC, "recette du drive tout nu"],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print(f"[pipeline] ✅ Notification envoyée")
            # Afficher la sortie du script pour debug
            if result.stdout.strip():
                print(f"[pipeline]     {result.stdout.strip()}")
        else:
            print(f"[pipeline] ❌ Erreur ntfy-send-url.sh : {result.stderr[:500]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[pipeline] ❌ Timeout ntfy-send-url.sh", file=sys.stderr)
    except Exception as e:
        print(f"[pipeline] ❌ ntfy error: {e}", file=sys.stderr)

DATE = datetime.now(PARIS_TZ).strftime("%Y-%m-%d")
def run(cmd: list[str]) -> bool:
    """Lance une commande, retourne True si succès."""
    print(f"[pipeline] $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[pipeline] ❌ Erreur : {result.stderr[:500]}", file=sys.stderr)
        return False
    # Afficher stdout pour debug
    if result.stdout.strip():
        print(f"[pipeline] {result.stdout.strip()}")
    return True
def main() -> int:
    print(f"[pipeline] === Pipeline quotidien {DATE} ===")

    # 1. Catalogue
    if not (BASE / "data" / "catalogue" / f"snapshot_{DATE}.json").exists():
        print(f"[pipeline] Catalogue absent, collecte en cours...")
        if not run(["python3", str(BASE / "agents" / "agent_catalogue.py")]):
            return 1
    else:
        print(f"[pipeline] Catalogue présent (snapshot_{DATE}.json)")

    # 2. Recettes (LLM + fallback)
    print(f"[pipeline] Génération des recettes (LLM + fallback Marmiton)...")
    # Augmenter --count pour avoir suffisamment de recettes après filtrage (desserts, temps, prix)
    if not run(["python3", str(BASE / "agents" / "agent_recettes_llm_v2.py"), "--count", "30"]):
        return 1

    # 3. Propositions
    print(f"[pipeline] Matching + filtres + propositions...")
    # Forcer le rafraîchissement pour utiliser les nouvelles recettes LLM
    if not run(["python3", str(BASE / "cli" / "generate_recipes.py"), "--json", "--refresh"]):
        return 1

    # 4. Rapport Markdown
    print(f"[pipeline] Génération du rapport Markdown...")
    if not run(["python3", str(BASE / "cli" / "generate_report.py")]):
        return 1

    # Synthèse
    print()
    print(f"[pipeline] === Pipeline terminé ===")
    print(f"[pipeline] Catalogue : data/catalogue/snapshot_{DATE}.json")
    print(f"[pipeline] Recettes : data/recettes/recettes_{DATE}.json")
    print(f"[pipeline] Rapport : data/reports/recettes_{DATE}.md")

    # Envoi ntfy.sh avec viewer
    print(f"[pipeline] Envoi du rapport par ntfy.sh (viewer)...")
    report_path = BASE / "data" / "reports" / f"recettes_{DATE}.md"
    if report_path.exists():
        send_ntfy_with_viewer(report_path)
    else:
        print(f"[pipeline] ❌ Rapport introuvable, pas d'envoi ntfy", file=sys.stderr)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
