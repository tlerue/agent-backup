---
name: courses-recettes
description: Point d'entrée consolidé du projet Courses & Recettes (drive Le Drivé Tout Nu, Beauzelle) — état du pipeline du jour, exécution de la chaîne complète (catalogue UCP/products.json + recettes LLM créatives + matching + propositions), panier UCP après validation humaine uniquement, et routage vers les skills spécialisés (base d'articles, idées de recettes).
version: 0.1.0
---

# Courses & Recettes — Pipeline consolidé

Point d'entrée unique du projet : affiche l'état du pipeline du jour, exécute la chaîne quotidienne complète (catalogue → recettes → propositions), crée le panier drive **après validation humaine explicite uniquement**, et route vers les skills spécialisés.

**Ce que ce skill ne fait JAMAIS** : aucun paiement, aucun checkout, aucune complétion de commande (liste blanche client : `complete_checkout`/`update_checkout`/`cancel_checkout`/`get_order` interdits — test négatif systématique) ; pas de panier sans `--confirm` ; pas de scraping du drive (UCP + flux public products.json) ; pas de relance en boucle sur rate-limit 429 du marchand (~30 min d'attente).

## When to Use

- « Où on en est du pipeline courses-recettes ? » → tableau de bord
- « Lance la chaîne du jour » / « mets à jour les données » → exécution complète
- « Crée-moi le panier pour le gratin de potimarron » → aperçu puis validation
- « Les données sont-elles fraîches ? » → vérification avant usage des skills
- Toute question globale sur le projet — ce skill route vers :
  - **articles** (prix, dispo, liste) → skill `courses-recettes-catalogue`
  - **idées de recettes** (propositions, détails, filtres) → skill `courses-recettes-idees`

## Prerequisites

- Python 3.12 (module standard uniquement — httpx installé si besoin réseau).
- `/home/user/courses-recettes` avec `agents/`, `cli/`, `data/`, `logs/`, `tests/`.
- Profil d'agent UCP hébergé GitHub (tlerue/ucp-agent-profile via jsDelivr — résolution auto du SHA).
- Accès réseau : `beauzelle.ledrivetoutnu.com` (drive), `www.marmiton.org` (recettes), `api.github.com` + `cdn.jsdelivr.net` (profil UCP).

## How to Run

1. `cd /home/user/courses-recettes`
2. **État du pipeline** : `python3 cli/status.py` — fraîcheur des 3 maillons + paniers archivés, aucun réseau.
3. **Verdict du dernier run** : `python3 agents/run_pipeline.py --status` — verdict une ligne + détail par maillon depuis `data/dernier_run.json`.
4. **Chaîne du jour** (~2 min, durcie) : `python3 agents/run_pipeline.py`
   - Orchestrateur avec seuils de qualité (catalogue ≥100, recettes ≥10, propositions ≥3 — « réussi mais vide » = échec), arrêt au premier maillon KO, verdict 🟢/🟠/🔴, journal `logs/runs/<date>.md`.
   - **Mode par défaut** : LLM (recettes créatives, prompt `agents/prompts/recette_creative.txt`). Seuil recettes ≥5 au lieu de ≥10.
   - **Mode Marmiton** (fallback) : `python3 agents/run_pipeline.py --marmiton`.
   - **Automatisation active** : chaîne lancée chaque matin 07:00 (Europe/Paris) — en cas d'échec, le verdict (🟠/🔴 + cause) est posté dans le chat du matin. Les agents ne sont PAS à relancer manuellement le matin même ; si besoin : un seul essai, jamais en boucle.
5. Si le run du matin a échoué : les CLI servent les données d'hier AVEC garde stale-data (⚠ DONNÉES STALE affiché) ; l'agent panier REFUSE --confirm sur données périmées (--confirm-stale pour forcer, déconseillé).
4. **Panier** (deux temps, jamais en un seul) :
   - Aperçu (local, zéro réseau) : `python3 agents/agent_panier.py --recette "gratin potimarron"`
   - Création réelle : ajouter `--confirm` — UNIQUEMENT après accord explicite de l'utilisateur en conversation.
5. **Tests qualité** : `python3 tests/test_matching.py` (34/34 verts attendus).

## Quick Reference

- Agents : `run_pipeline.py` (orchestrateur durci — verdict + dernier_run.json) · `agent_catalogue.py` (hybride products.json + UCP échantillon, arrêt au 429) · `agent_recettes_llm.py` (**par défaut**, génération LLM avec prompt `prompts/recette_creative.txt`) · `agent_recettes.py` (Marmiton fallback `--marmiton`) · `agent_matching.py` (filtre viande familial titre+ingrédients, quantités, brut vs transformé, homonymes pâte/pâtes) · `agent_panier.py` (GID normalisés, `--confirm` obligatoire, **refus --confirm si données stale** sauf --confirm-stale).
- CLI : `status.py` (tableau de bord) · `query_catalogue.py` (articles, garde stale) · `query_recettes.py` (propositions, `--detail`, `--max-prepa`, `--cov`, `--max-prix`, garde stale).
- Santé du run : `data/dernier_run.json` (verdict, statut/durée/erreur par maillon) · `logs/runs/<date>.md` (journal consolidé).
- Données du jour : `data/{catalogue,recettes,propositions}/…_<date>.json` · Paniers : `data/paniers/panier_<date>_<slug>.json` + `logs/paniers_<date>.md`.
- **Règles familiales appliquées partout** : pas de viande (titre + ingrédients) ; poisson OK ; bouillons cube OK (toute espèce) ; bouillon de volaille toute forme OK (liquide validé) ; bœuf liquide et bouillons d'os exclus ; « haché » = viande seulement après un mot viande.
- Prix UCP en centimes (ISO 4217) — convertis en euros côté pipeline. Totals serveur = source de vérité après création du panier.

## Procedure

1. **État** — lancer `status.py` d'abord. Si 🟢 : les données du jour existent, interroger directement (`query_recettes.py` / skill spécialisé). Si 🟠/❌ : enchaîner les agents manquants (étape 3).
2. **Chaîne** — exécuter les 3 agents dans l'ordre ; vérifier `[matching] ~25 propositions` en sortie. Un 429 UCP pendant le catalogue est ATTENDU (budget discovery du marchand) : le socle products.json prend le relais — ne pas relancer dans la même demi-heure.
3. **Panier — validation obligatoire en deux temps** :
   a. Aperçu : `agent_panier.py --recette "<mots du titre>"` → présenter le récapitulatif à l'utilisateur (produits, quantités, total estimé).
   b. Demander l'accord explicite en conversation (« je crée le panier ? »). **Seulement après réponse positive** : relancer avec `--confirm`. Ne jamais enchaîner aperçu+confirm d'un seul tenant sans accord.
   c. Restituer : cart_id, totaux SERVEUR, `continue_url` (permalink à ouvrir pour finalisation MANUELLE — le paiement se fait par l'humain sur le site, jamais via le pipeline).
4. **Routage** — questions articles → skill `courses-recettes-catalogue` ; questions recettes/propositions → skill `courses-recettes-idees` ; ce skill reste le point d'entrée des demandes transverses (état, chaîne, panier).
5. **Réponse** — toujours en français, avec les chiffres réels (produits, €, minutes). Ne jamais inventer un prix, une disponibilité ou un total : lire les JSON du jour ou les totaux serveur.

## Pitfalls

- **JAMAIS de `--confirm` sans accord explicite** de l'utilisateur dans la conversation en cours.
- **Jamais de panier « au cas où »** : un aperçu ne crée rien ; chaque `--confirm` crée un panier réel chez le marchand (archivé et traçable).
- **`complete_checkout` et frères** : interdits par la liste blanche du client — si un appel est tenté, `UcpForbiddenCall` lève une erreur et l'agent s'arrête ; ne pas contourner.
- **429 UCP** : arrêt immédiat de la passe UCP (`Retry-After` ~30 min) ; le socle products.json couvre le catalogue ; le panier nécessite l'UCP — si 429, réessayer plus tard.
- **GID** : `create_cart` exige `gid://shopify/ProductVariant/<id>` — normalisation automatique (`to_variant_gid`) ; une erreur « is not a valid ProductVariant GID » signifie un ID nu passé en direct (ne pas le faire).
- **Ancres multi-mots** : « courge spaghetti » doit rester EN TÊTE des ancres (sinon privée de son tour par le plafond de 40 recettes — bug mesuré).
- **Données périmées** : les propositions datées d'hier ne reflètent pas le drive du jour — vérifier `status.py` avant de conseiller un panier.
- **Recherche de proposition** : par mots présents (« gratin potimarron » → « Gratin de potimarron ») — pas de sous-chaîne exacte.
- **Mode par défaut** : LLM activé automatiquement (`agent_recettes_llm.py` + prompt `recette_creative.txt`). Vérifier `LLM_API_URL` et `LLM_MODEL` env vars avant lancement. Si le LLM est injoignable → le maillon recipes échoue (pas de fallback Marmiton automatique).
- **Mode Marmiton fallback** : `--marmiton` sur `run_pipeline.py` active `agent_recettes.py` (scraping Marmiton).
- **Évaluation** : `python3 agents/eval_recettes.py` compare recettes LLM vs Marmiton (créativité, couverture, faisabilité, conformité familiale). Sortie : `data/eval/eval_<date>.json`.

## Verification

```bash
cd /home/user/courses-recettes
python3 cli/status.py
python3 tests/test_matching.py | tail -2
```

Succès si : `status.py` affiche 🟢 (données du jour) ou indique précisément le maillon manquant ; les tests affichent « 0 échec(s) ». Pour un panier : l'archive `data/paniers/panier_<date>_<slug>.json` existe et contient `cart_id` + `continue_url` + totaux serveur.
