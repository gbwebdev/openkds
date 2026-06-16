#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
#  OpenKDS — Mise à jour bare-metal
#  Usage : sudo bash update.sh
#
#  Doit être exécuté depuis le dossier où vous avez initialement cloné le repo.
#  Le script fait un git pull, synchronise vers /opt/openkds, réinstalle le
#  package Python et redémarre le service. Préserve config.json et openkds.db.
# ═══════════════════════════════════════════════════════════════════════════════

INSTALL_DIR="/opt/openkds"
SERVICE_USER="openkds"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${YELLOW}══ $* ══${NC}"; }

[ "$(id -u)" -eq 0 ] || error "Ce script doit être exécuté en root (sudo bash update.sh)"
[ -d "$INSTALL_DIR" ] || error "$INSTALL_DIR n'existe pas — lancez install.sh d'abord"

# ── 1. Pull du code source ────────────────────────────────────────────────────
step "Récupération du code"

if [ -d "$SCRIPT_DIR/.git" ]; then
    git -C "$SCRIPT_DIR" pull --ff-only || error "git pull a échoué"
    info "Code à jour : $(git -C "$SCRIPT_DIR" log -1 --oneline)"
else
    warn "Pas de dépôt git dans $SCRIPT_DIR — synchronisation directe depuis les sources existantes"
fi

# ── 2. Synchronisation vers $INSTALL_DIR ──────────────────────────────────────
step "Synchronisation vers $INSTALL_DIR"

# --delete pour supprimer les fichiers obsolètes (renommages/suppressions)
# data/, venv/, .git/ et les .db sont préservés
rsync -a --delete \
    --exclude='venv/' \
    --exclude='data/' \
    --exclude='.git/' \
    --exclude='*.db' \
    --exclude='__pycache__' \
    --exclude='.github/' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
info "Fichiers synchronisés"

# ── 3. Réinstallation du package Python ───────────────────────────────────────
step "Mise à jour du package Python"

"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet "$INSTALL_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"
info "Package installé"

# ── 4. Redémarrage du service ─────────────────────────────────────────────────
step "Redémarrage du service"

systemctl restart openkds
sleep 1

if systemctl is-active --quiet openkds; then
    info "Service openkds actif"
else
    error "Service openkds ne démarre pas — vérifier : journalctl -u openkds -n 50"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Mise à jour terminée avec succès    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo -e "  Logs en direct : ${YELLOW}journalctl -u openkds -f${NC}"
echo ""
