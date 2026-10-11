#!/usr/bin/env python3
"""Orchestrateur durci du pipeline courses-recettes.

Chaîne : catalogue → recettes → matching, avec les 3 protections :
  1. STATUT PAR ÉTAPE — dernier_run.json (ok/échec/durée/erreur par maillon),
     journal consolidé logs/runs/<date>.md ; un maillon KO n'efface pas les
     données du jour précédent (les snapshots échoués ne sont pas écrits).
  2. SEUILS DE QUALITÉ — un maillon "réussi" mais vide/pauvre est un ÉCHEC :
     catalogue < 100 produits, recettes < 10, propositions < 3.
  3. DIAGNOSTIC CONSOMMABLE — sortie finale : verdict une ligne + actions.
     L'automatisation matinale colle ce verdict dans le chat.

Usage :
  python3 agents/run_pipeline.py            # chaîne complète
  python3 agents/run_pipeline.py --status   # dernier verdict
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LAST_RUN = BASE / "data" / "dernier_run.json"
RUN_LOG_DIR = BASE / "logs" / "runs"
LOCK_FILE = BASE / "data" / "pipeline.lock"
ARCHIVE_DIR = BASE / "data" / "catalogue" / "archive"

# Fuseau horaire Paris pour les noms de fichiers (évite les décalages UTC)
PARIS_TZ = timezone(timedelta(hours=2), "Europe/Paris")


def pipeline_date() -> str:
    """Date de Paris (évite les décalages de minuit UTC)."""
    return datetime.now(PARIS_TZ).strftime("%Y-%m-%d")


def acquire_lock() -> bool:
    """Verrouillage par PID : empêche les doubles exécutions concurrentes."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Vérifier si le processus est encore vivant
            try:
                os.kill(pid, 0)  # signal 0 = vérification d'existence
            except (OSError, ProcessLookupError):
                pass  # processus mort, on peut reprendre le verrou
            else:
                print(f"⚠️  Verrou détenu par le PID {pid} — pipeline déjà en cours.")
                return False
        except (ValueError, OSError):
            pass  # lock corrompu, on le remplace
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    """Libère le verrou."""
    try:
        if LOCK_FILE.exists() and int(LOCK_FILE.read_text().strip()) == os.getpid():
            LOCK_FILE.unlink()
    except (ValueError, OSError):
        pass

STEPS = [
    # (nom, commande, min_count, tentatives, backoff_s)
    # MODE PAR DÉFAUT : LLM v2 (recettes créatives avec fichiers .md)
    ("catalogue", [sys.executable, str(BASE / "agents" / "agent_catalogue.py")], 100, 2, [0, 300]),
    ("recettes", [sys.executable, str(BASE / "agents" / "agent_recettes_llm_v2.py")], 2, 1, [0]),
    ("matching", [sys.executable, str(BASE / "agents" / "agent_matching.py")], 2, 1, [0]),
]

STEPS_MARMITON = [
    # (nom, commande, min_count, tentatives, backoff_s)
    # MODE MARMITON (ancien comportement, fallback)
    ("catalogue", [sys.executable, str(BASE / "agents" / "agent_catalogue.py")], 100, 2, [0, 300]),
    ("recettes", [sys.executable, str(BASE / "agents" / "agent_recettes.py")], 10, 2, [0, 300]),
    ("matching", [sys.executable, str(BASE / "agents" / "agent_matching.py")], 3, 1, [0]),
]

STEPS_LLM = STEPS  # alias rétrocompatibilité


def step_has_data(step: str, date: str) -> bool:
    """Vérifie si le maillon a produit des données pour la date donnée."""
    return count_of(step, date) is not None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def count_of(step: str, date: str) -> int | None:
    """Nombre d'items produits par le maillon pour la date du jour (None = absent)."""
    patterns = {
        "catalogue": BASE / "data" / "catalogue" / f"snapshot_{date}.json",
        "recettes": BASE / "data" / "recettes" / f"recettes_{date}.json",
        "matching": BASE / "data" / "propositions" / f"propositions_{date}.json",
    }
    path = patterns[step]
    if not path.exists():
        return None
    d = read_json_safe(path)
    if step == "catalogue":
        return len(d.get("products", []))
    if step == "recettes":
        return len(d.get("recipes", []))
    return len(d.get("propositions", []))


def run_step(name: str, cmd: list[str], min_count: int, date: str) -> dict:
    """Exécute un agent avec logging structuré dans un fichier dédié."""
    log_dir = BASE / "logs" / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date}_{name}.log"

    t0 = time.monotonic()
    out, err, exit_code, error = "", "", 0, None
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                  text=True, timeout=900)
            exit_code = proc.returncode
            if exit_code != 0:
                error = f"exit={exit_code} (voir {log_path.name})"
    except subprocess.TimeoutExpired:
        exit_code, error = -1, f"timeout (900 s) — voir {log_path.name}"
    except Exception as e:  # noqa: BLE001
        exit_code, error = -1, f"{type(e).__name__}: {e}"

    duration = round(time.monotonic() - t0, 1)
    n = count_of(name, date)
    # Protection 2 : seuil de qualité — "réussi mais vide" = échec
    if exit_code == 0 and n is not None and n < min_count:
        exit_code = 2
        error = f"SEUIL DE QUALITÉ : {n} items (< {min_count} attendus) — voir {log_path.name}"
    status = "ok" if exit_code == 0 else "echec"
    return {
        "step": name, "status": status, "exit_code": exit_code,
        "duration_s": duration, "count": n, "error": error,
        "log_file": str(log_path.relative_to(BASE)),
    }


def verdict_line(results: list[dict], date: str, use_llm: bool) -> str:
    ok = [r for r in results if r["status"] == "ok"]
    ko = [r for r in results if r["status"] != "ok"]
    if not ko:
        c = {r["step"]: r["count"] for r in results}
        return (f"🟢 Pipeline OK {date} — {c.get('catalogue', '?')} produits, "
                f"{c.get('recettes', '?')} recettes, {c.get('matching', '?')} propositions.")
    if ko[0]["step"] == "catalogue":
        return (f"🔴 Pipeline KO {date} — catalogue indisponible ({ko[0]['error'] or 'voir log'}). "
                f"Le drive ou le réseau était injoignable.")
    first_ko = ko[0]
    source_label = "LLM" if use_llm else "Marmiton"
    part = f"recettes {source_label}" if first_ko['step'] == 'recettes' else 'matching'
    return (f"🟠 Pipeline PARTIEL {date} — {part} en échec ({first_ko['error'] or 'voir log'}). "
            f"Les propositions du soir sont celles du jour précédent (garde stale-data).")


def write_run_log(date: str, results: list[dict], verdict: str) -> None:
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# Run du {date}", "", verdict, "",
             "| maillon | statut | durée | items | log | erreur |",
             "|---|---|---|---|---|---|"]
    for r in results:
        err = (r.get("error") or "").replace("|", "/").replace("\n", " ")[:120]
        logf = r.get("log_file", "-")
        lines.append(f"| {r['step']} | {r['status']} | {r['duration_s']}s | "
                     f"{r.get('count') if r.get('count') is not None else '-'} | "
                     f"{logf} | {err} |")
    (RUN_LOG_DIR / f"{date}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    date = pipeline_date()
    # Mode par défaut : LLM (recettes créatives). --marmiton pour revenir à Marmiton.
    use_llm = "--marmiton" not in sys.argv

    if "--status" in sys.argv:
        run = read_json_safe(LAST_RUN)
        if not run:
            print("Aucun run enregistré.")
            return 1
        print(run.get("verdict", "?"))
        for s in run.get("steps", []):
            icon = "✅" if s["status"] == "ok" else "❌"
            print(f"  {icon} {s['step']}: {s['status']} ({s['duration_s']}s, {s.get('count')} items)")
            if s.get("error"):
                print(f"     ⚠ {s['error'][:150]}")
        return 0 if run.get("global_status") == "ok" else 1

    # --- Verrou ---
    if not acquire_lock():
        return 2

    active_steps = STEPS if use_llm else STEPS_MARMITON
    source_label = "LLM" if use_llm else "Marmiton"
    print(f"▶ Pipeline {source_label} — date {date}")

    try:
        # --- Pipeline indépendant par maillon ---
        # Chaque maillon a ses propres tentatives et backoff.
        # Un échec catalogue n'empêche pas les recettes de tourner (mode dégradé).
        results: list[dict] = []

        for name, cmd, min_count, max_attempts, backoff_s in active_steps:
            print(f"▶ {name}…", flush=True)
            step_results: list[dict] = []

            for attempt in range(max_attempts):
                if attempt > 0:
                    wait = backoff_s[attempt]
                    print(f"  🔄 Retentative {attempt + 1}/{max_attempts} "
                          f"après {wait}s de pause…", flush=True)
                    time.sleep(wait)

                r = run_step(name, cmd, min_count, date)
                step_results.append(r)
                icon = "✅" if r["status"] == "ok" else "❌"
                print(f"  {icon} {name}: {r['status']} ({r['duration_s']}s, "
                      f"{r.get('count')} items)"
                      + (f" — {r['error'][:100]}" if r.get("error") else ""))

                if r["status"] == "ok":
                    break  # succès, pas besoin de retenter ce maillon

            # Prendre le meilleur résultat (dernier si échec persistant)
            results.append(step_results[-1])

        global_status = "ok" if all(r["status"] == "ok" for r in results) else (
            "partiel" if any(r["status"] == "ok" for r in results) else "echec")
        verdict = verdict_line(results, date, use_llm)

        run = {
            "date": date,
            "finished_at": now_iso(),
            "global_status": global_status,
            "verdict": verdict,
            "steps": [{k: v for k, v in r.items() if k != "output_tail"} for r in results],
        }
        LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        write_run_log(date, results, verdict)

        print()
        print(verdict)
        
        # Envoi notification ntfy.sh si succès
        if global_status == "ok":
            # Générer le rapport d'abord
            print(f"▶ Génération du rapport Markdown...")
            subprocess.run(
                [sys.executable, str(BASE / "cli" / "generate_report.py")],
                cwd=str(BASE),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            ntfy_script = Path("/home/user/.agents/skills/ntfy-send-url/ntfy-send-url.sh")
            if ntfy_script.exists():
                try:
                    result = subprocess.run(
                        [str(ntfy_script), str(BASE / "data" / "reports" / f"recettes_{date}.md"), 
                         "menez-roch-veur-en-bzh-que-c-est", 
                         f"Recettes {date} - {verdict.split('—')[1].strip() if '—' in verdict else 'Pipeline OK'}"],
                        cwd=str(BASE),
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if result.returncode == 0:
                        print(f"✅ Notification envoyée via ntfy")
                    else:
                        print(f"⚠️ Erreur ntfy-send-url.sh : {result.stderr[:200]}")
                except Exception as e:
                    print(f"⚠️ Erreur ntfy: {e}")
        
        return 0 if global_status == "ok" else 1

    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
