#!/bin/bash
# send-md-ntfy.sh — Envoie un fichier .md sur GitHub, puis une notif ntfy.sh avec viewer intégré
# Usage : ./send-md-ntfy.sh <path.md> <topic-ntfy> <texte-notif>
#
# Format d'URL corrigé : https://tlerue.github.io/ntfy-md-notif/viewer.html?url=https://raw.githubusercontent.com/tlerue/ntfy-md-notif/main/recettes_YYYY-MM-DD.md
# Supprime la notification {"subscribe": "true"} qui était indésirable

set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Usage : $0 <path.md> <topic-ntfy> <texte-notif>" >&2
    echo "Exemple : $0 /home/user/courses-recettes/data/reports/recettes_2026-10-07.md menez-roch-veur-en-bzh-suivi-google-maps-que-c-est \"Nouveau rapport disponible\"" >&2
    exit 1
fi

MD_PATH="$1"
NTFY_TOPIC="$2"
NTFY_TEXT="$3"

# Validations de base
if [ ! -f "$MD_PATH" ]; then
    echo "ERREUR : fichier introuvable : $MD_PATH" >&2
    exit 2
fi

REPO_DIR="/home/user/.agents/scripts/ntfy-md-notif"
BRANCH_NAME="main"

# Vérifier/initialiser le repo local
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Initialisation du dépôt local..."
    git clone https://github.com/tlerue/ntfy-md-notif.git "$REPO_DIR"
fi

cd "$REPO_DIR"

# Config git si nécessaire
if ! git config user.name >/dev/null 2>&1; then
    git config --global user.name "unknown"
    git config --global user.email "unknown@localhost"
fi

# Synchroniser avec le remote
echo "Récupération des dernières modifications..."
git fetch origin "$BRANCH_NAME" 2>/dev/null || true
git checkout "$BRANCH_NAME"
git pull origin "$BRANCH_NAME" --ff-only || true

# Préparer les credentials GitHub
cd "$REPO_DIR"
GITHUB_PAT=""
if [ -f "$HOME/.gh_token" ]; then
    GITHUB_PAT=$(grep -v '^#' "$HOME/.gh_token" | tr -d '\n' | tr -d ' ')
fi
if [ -z "$GITHUB_PAT" ]; then
    echo "⚠️ AVERTISSEMENT : pas de GitHub PAT trouvé dans ~/.gh_token"
    echo "   Veuillez créer le fichier ~/.gh_token avec votre Personal Access Token GitHub."
    echo "   Exemple : echo 'github_pat_...' > ~/.gh_token"
    echo "   Le push échouera sans credentials valides."
fi

# Copier le fichier .md dans le repo (en remplaçant le fichier existant si présent)
TARGET_NAME="recettes_$(date +%Y-%m-%d).md"
cp "$MD_PATH" "$REPO_DIR/$TARGET_NAME"

# S’assurer que git voit le changement même si le contenu est identique
echo "Commit et push du fichier $TARGET_NAME..."
git add --force "$TARGET_NAME"
git commit --allow-empty -m "Mise à jour rapport $TARGET_NAME $(date -Iseconds)"

if [ -n "$GITHUB_PAT" ]; then
    git remote set-url origin "https://tlerue:${GITHUB_PAT}@github.com/tlerue/ntfy-md-notif.git"
    echo "Push avec authentification PAT..."
else
    echo "⚠️ Push sans authentification (doit être fait manuellement)"
fi
git push origin "$BRANCH_NAME" || { echo "❌ Erreur lors du push (PAT invalide ou repo inaccessible)"; exit 3; }

# Construire l'URL brute GitHub
RAW_URL="https://raw.githubusercontent.com/tlerue/ntfy-md-notif/$BRANCH_NAME/$TARGET_NAME"
VIEWER_URL="https://tlerue.github.io/ntfy-md-notif/viewer.html?url=$RAW_URL"

# Envoyer la notif ntfy.sh avec boutons intégrés
echo "Envoi de la notification sur ntfy.sh/$NTFY_TOPIC"

# Construire le JSON pour les actions (boutons) avec jq (mode compact -c pour une ligne)
# IMPORTANT : message et actions doivent être à la même racine (pas dans message)
JSON_PAYLOAD=$(jq -c --arg msg "$NTFY_TEXT" --arg viewer "$VIEWER_URL" --arg raw "$RAW_URL" '{
  "message": $msg,
  "actions": [
    {
      "label": "🚀 Ouvrir le rapport",
      "action": "view",
      "url": $viewer
    },
    {
      "label": "📋 Copier le lien",
      "action": "copy",
      "body": $viewer
    },
    {
      "label": "👁️ Vue brute",
      "action": "view",
      "url": $raw
    }
  ]
}')

echo "Payload JSON : $JSON_PAYLOAD"

echo "$JSON_PAYLOAD" | curl -s -X POST "https://ntfy.sh/$NTFY_TOPIC" \
  -H "Title: $NTFY_TEXT" \
  -H "Tags: report" \
  -H "Priority: default" \
  -H "Content-Type: application/json" \
  -d @- || { echo "ERREUR lors de l'envoi de la notification"; exit 4; }

echo "✅ Terminé : $VIEWER_URL"
