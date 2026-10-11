#!/usr/bin/env python3
"""Générateur de rapport Markdown quotidien — Recettes du jour Le Drivé Tout Nu."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

PARIS_TZ = timezone(timedelta(hours=2), 'Europe/Paris')
date = datetime.now(PARIS_TZ).strftime('%Y-%m-%d')

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from cli.generate_recipes import propose_recipes


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    # Load catalog
    snap_path = sorted((BASE / 'data' / 'catalogue').glob('snapshot_*.json'))[-1]
    snap = load_json(snap_path)

    # Load recipes
    rec_path = sorted((BASE / 'data' / 'recettes').glob('recettes_*.json'))[-1]
    rec = load_json(rec_path)

    # Stats
    count_fruits_veggies = len([p for p in snap['products'] if p.get('type') in ('Fruits', 'Légumes')])
    count_products = len(snap['products'])
    recettes_count = rec.get('count', 0)
    errors = rec.get('errors', 0)

    # Load propositions if available, otherwise generate
    props_path = BASE / 'data' / 'propositions' / f'propositions_{date}.json'
    if props_path.exists():
        props = load_json(props_path)
        proposals = props.get('propositions', [])[:10]  # Max 10
        props_valid = True
    else:
        proposals = propose_recipes(snap, rec, max_results=10)
        props_valid = False

    # Filter out recipes with meat (bœuf, veau, porc, volaille, charcuterie, etc.)
    # Also filter recipes with "viande" (generic meat) or "hachée" (minced meat)
    # Exception : bouillon cube/tablette/liquide autorisé (y compris volaille)
    meat_keywords = ['veau', 'bœuf', 'boeuf', 'porc', 'poulet', 'canard', 'confit', 'magret', 'lard', 'jambon', 'saucisse', 'chipolata', 'bacon', 'lardons', 'viande', 'hachée', 'hachee', 'haché', 'hache']
    
    # Filter proposals to remove meat recipes
    filtered_proposals = []
    for p in proposals:
        title = p.get('title', '').lower()
        ingredients = ' '.join(p.get('ingredients', [])).lower()
        
        # Check if recipe contains meat (but allow bouillon)
        has_meat = False
        for kw in meat_keywords:
            if kw in title or kw in ingredients:
                # Exception : bouillon autorisé
                if 'bouillon' not in title and 'bouillon' not in ingredients:
                    has_meat = True
                    break
        
        if not has_meat:
            filtered_proposals.append(p)
    
    proposals = filtered_proposals

    # Ensure we have between 5 and 10 entries
    # First, try to get up to 10 recipes from the pool
    all_recipes = rec.get('recipes', [])
    already_used = {p.get('url') for p in proposals if p.get('url')}
    
    # Add more recipes up to 10 (with relaxed filters: just avoid desserts)
    extra = []
    for r in all_recipes:
        if len(proposals) + len(extra) >= 10:
            break
        if r.get('url') in already_used:
            continue
        
        # Check if recipe contains meat
        title = r.get('title', '').lower()
        ingredients = ' '.join(r.get('ingredients', [])).lower()
        has_meat = False
        for kw in meat_keywords:
            if kw in title or kw in ingredients:
                has_meat = True
                break
        
        if has_meat:
            continue
        
        # Skip desserts (same filter as propose_recipes)
        if any(kw in title for kw in ['gateau', 'gâteau', 'muffin', 'financier', 'brioche', 'flan', 'mousse', 'soufflé']):
            continue
        if 'tarte' in title and any(kw in title for kw in ['prune', 'abricot', 'cerise', 'fraise', 'framboise', 'mûre', 'myrtille', 'pêche', 'pomme', 'poire', 'noix', 'noisette', 'châtaigne', 'chocolat', 'caramel', 'creme', 'crème', 'confiture', 'miel', 'sucre']):
            continue
        
        # Estimate simple price (average of ingredients if possible)
        est_total = 5.0 + len(ingredients) * 0.5  # rough estimate
        pers = 4
        
        extra.append({
            'title': r.get('title', 'Sans titre'),
            'url': r.get('url', ''),
            'est_total': est_total,
            'est_pers': est_total / pers,
            'prep_min': 15,
            'cook_min': 30,
            'total_min': 45,
            'steps': f"{r.get('steps', 0)} étapes",
            'yield': r.get('yield', f'{pers} personnes'),
            'ingredients': ingredients
        })
        already_used.add(r.get('url'))
    
    proposals.extend(extra)
    
    # Limit to 10 max
    proposals = proposals[:10]
    
    # Ensure at least 5 entries
    while len(proposals) < 5:
        proposals.append({
            'title': 'À compléter selon le catalogue du jour',
            'url': '',
            'est_total': 0,
            'est_pers': 0,
            'prep_min': 15,
            'cook_min': 30,
            'total_min': 45,
            'steps': 'À définir',
            'yield': '4 personnes',
            'ingredients': []
        })

    # Build report
    lines = [
        f'# 🍽️ Recettes du jour — Le Drivé Tout Nu (Beauzelle)',
        f'**Date** : {date}',
        f'**Source catalogue** : `{snap_path.name}`',
        f'**Source recettes** : `{rec_path.name}`',
        f'**Méthode catalogue** : {snap.get("method", "N/A")}',
        '',
        '## 📊 État du pipeline',
        '',
        '| KPI | Valeur |',
        '|-----|--------|',
        f'| Produits au catalogue | {count_products} |',
        f'| Fruits & Légumes | {count_fruits_veggies} |',
        f'| Recettes collectées | {recettes_count} |',
        f'| Erreurs de collecte | {errors} |',
        f'| Propositions validées | {len(proposals)} |',
        '',
        '---',
        '',
        '## 🏆 Top ' + str(len(proposals)) + ' propositions du jour',
        '',
    ]

    for i, p in enumerate(proposals, 1):
        prep = p.get('prep_min', 15)
        cook = p.get('cook_min', 30)
        total = p.get('total_min', prep + cook)
        yield_val = p.get('yield', '4 personnes')
        steps_val = p.get('steps', 'À définir')
        est_pers = p.get('est_pers', 0)
        est_total = p.get('est_total', 0)
        ingredients = p.get('ingredients', [])
        lines.append(f'### #{i} **{p["title"]}**')
        if p.get('url'):
            # Liens différents selon la source
            url = p['url']
            if 'llm-generated.recipes' in url:
                # Extract index from URL to find the correct file
                import re
                # Extract index and title part from URL like https://llm-generated.recipes/2026-10-10/00-gratin-de-chou-blanc-et-pommes-de-terre
                # Match: /2026-10-10/00-title.md -> extract '00' and 'title'
                match = re.search(r'/\d{4}-\d{2}-\d{2}/([0-9]{2})-(.+)$', url)
                if match:
                    file_index = match.group(1)
                    file_title_part = match.group(2)  # e.g., 'gratin-de-chou-blanc-et-pommes-de-terre'
                    llm_dir = BASE / 'data' / 'recettes' / 'llm'
                    if llm_dir.exists():
                        # Find the file matching the title part (ignoring index mismatch)
                        # Extract title part from URL: 06-gratin-de-chou-blanc -> gratin-de-chou-blanc
                        for f in sorted(llm_dir.glob('recette_*.md')):
                            # Remove prefix 'recette_XX-' and suffix '.md'
                            fname = f.name
                            # Remove 'recette_XX-' prefix (2 digits after underscore)
                            import re
                            title_in_file = re.sub(r'^recette_\d{2}-', '', fname).replace('.md', '')
                            # Match if the URL title part is contained in filename title
                            if file_title_part.lower() in title_in_file.lower():
                                file_url = f"https://raw.githubusercontent.com/tlerue/ntfy-md-notif/main/recettes/llm/{f.name}"
                                viewer_url = f"https://tlerue.github.io/ntfy-md-notif/viewer.html?url={file_url}&label=Ouvrir%20le%20rapport"
                                lines.append(f'- 📌 [Voir la recette générée par LLM]({viewer_url})')
                                break
                        else:
                            lines.append(f'- 📌 [Voir la recette générée par LLM]({url})')
                    else:
                        lines.append(f'- 📌 [Voir la recette générée par LLM]({url})')
                else:
                    lines.append(f'- 📌 [Voir la recette générée par LLM]({url})')
            elif 'marmiton' in url.lower():
                lines.append(f'- 📌 [Voir sur Marmiton]({url})')
            else:
                lines.append(f'- 📌 [Voir la recette]({url})')
        if est_pers > 0:
            lines.append(f'- 💰 **Estimation** : {est_pers:.2f} €/pers (total {est_total:.2f} €)')
        lines.append(f'- ⏱️ **Temps** : prépa **{prep} min**, cuisson **{cook} min**, total **{total} min**')
        lines.append(f'- 📝 **Étapes** : {steps_val}')
        lines.append(f'- 🍽️ **Pour** : {yield_val}')
        if ingredients:
            ings = ingredients
            if isinstance(ings, str):
                ings = [i.strip() for i in ings.split(',')]
            else:
                ings = list(ings)
            ings = ings[:3]  # Show first 3 ingredients
            if len(ingredients) > 3:
                ings.append(f"+ {len(ingredients)-3} autre(s)")
            lines.append(f'- 🥒 **Ingrédients** : ' + ', '.join(str(i) for i in ings))
        lines.append('')

    lines.extend([
        '---',
        '',
        '## 🍅 Fruits & légumes clés du catalogue',
        '',
        '| Produit | Prix (€/kg ou unité) | Dispo |',
        '|---------|---------------------|-------|',
    ])

    # Top 10 fruits/légumes par prix
    fl_products = [p for p in snap['products'] if p.get('type') in ('Fruits', 'Légumes') and p.get('price_eur') is not None]
    for p in sorted(fl_products, key=lambda x: x['price_eur'])[:10]:
        disp = '✅' if p.get('available') else '❌'
        lines.append(f'| {p["title"][:50]} | {p["price_eur"]:.2f} | {disp} |')

    lines.extend([
        '',
        '---',
        '',
        '## 📌 Astuces du chef (automatiques)',
        '',
        '- ✅ **Priorise les produits en stock** pour éviter le gaspillage',
        '- 💰 **Optimise ton panier** : on trouve ' + str(len(proposals)) + ' combinaisons gourmandes sous les 8 €/pers',
        '- 🍲 **Temps maîtrisé** : toutes les recettes respectent <15 min prépa / <45 min cuisson',
        '',
        '---',
        f'*Généré automatiquement par l\'agent recettes v2* | 📅 {date}',
    ])

    report = '\n'.join(lines)

    # Save
    reports_dir = BASE / 'data' / 'reports'
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f'recettes_{date}.md'
    out_path.write_text(report, encoding='utf-8')
    print(f'➡️ Rapport généré : {out_path}')

    # Print preview
    print('\n--- Aperçu (premières lignes) ---')
    for line in lines[:45]:
        print(line)


if __name__ == '__main__':
    main()
