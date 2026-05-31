#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
#  Bazaar — Script d'installation complet
#  À exécuter une seule fois en root sur la machine cible (Raspberry Pi ou PC).
#  Usage : sudo bash install.sh
# ═══════════════════════════════════════════════════════════════════════════════

INSTALL_DIR="/opt/bazaar"
SERVICE_USER="bazaar"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"
SSID="${SSID:-Bazaar2026}"
PASSPHRASE="${PASSPHRASE:-bazaar2026}"
SERVER_IP="192.168.50.1"
DHCP_START="192.168.50.10"
DHCP_END="192.168.50.50"

# Chemin du dossier contenant ce script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${YELLOW}══ $* ══${NC}"; }

[ "$(id -u)" -eq 0 ] || error "Ce script doit être exécuté en root (sudo bash install.sh)"

# ── 1. Dépendances système ────────────────────────────────────────────────────
step "Installation des dépendances système"

apt-get update -q
apt-get install -y \
    python3 python3-pip python3-venv \
    hostapd dnsmasq \
    libusb-1.0-0 \
    rfkill
info "Dépendances installées"

# Débloquer le WiFi (Raspberry Pi le bloque par défaut)
rfkill unblock wifi 2>/dev/null || true

# ── 2. Utilisateur système ────────────────────────────────────────────────────
step "Création de l'utilisateur système"

if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    info "Utilisateur '$SERVICE_USER' créé"
else
    info "Utilisateur '$SERVICE_USER' déjà existant"
fi

# ── 3. Déploiement des fichiers ───────────────────────────────────────────────
step "Déploiement dans $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"
# Copie des sources (on exclut venv et db existante)
rsync -a --exclude='venv/' --exclude='bazaar.db' "$SCRIPT_DIR/" "$INSTALL_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
info "Fichiers copiés"

# ── 4. Environnement Python ───────────────────────────────────────────────────
step "Création du virtualenv Python"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"
info "Virtualenv prêt"

# ── 5. Règles udev pour les imprimantes USB ───────────────────────────────────
step "Règles udev imprimantes USB"

cat > /etc/udev/rules.d/99-bazaar-printers.rules <<'EOF'
# Imprimantes thermiques — accès pour l'utilisateur bazaar
# Epson TM series
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", GROUP="bazaar", MODE="0660"
# Generic / autres vendeurs (à compléter après lsusb)
SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:07*", GROUP="bazaar", MODE="0660"
EOF

usermod -aG plugdev "$SERVICE_USER" 2>/dev/null || true
udevadm control --reload-rules
udevadm trigger
info "Règles udev installées"

# ── 6. Hotspot WiFi ───────────────────────────────────────────────────────────
step "Configuration du hotspot WiFi ($WIFI_IFACE)"

# Désactiver NetworkManager sur wlan0 pour éviter les conflits
if command -v nmcli &>/dev/null; then
    nmcli device set "$WIFI_IFACE" managed no 2>/dev/null || true
    # Persister via NetworkManager
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/bazaar-wifi.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${WIFI_IFACE}
EOF
    info "NetworkManager : $WIFI_IFACE marqué unmanaged"
fi

# IP statique sur wlan0
cat > /etc/network/interfaces.d/bazaar-wlan0 <<EOF
auto ${WIFI_IFACE}
iface ${WIFI_IFACE} inet static
    address ${SERVER_IP}
    netmask 255.255.255.0
EOF

# hostapd
cat > /etc/hostapd/hostapd.conf <<EOF
interface=${WIFI_IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSPHRASE}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Pointer hostapd vers sa config
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# dnsmasq
[ -f /etc/dnsmasq.conf.orig ] || cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
cat > /etc/dnsmasq.conf <<EOF
# Bazaar — DNS/DHCP pour le hotspot
interface=${WIFI_IFACE}
bind-interfaces
dhcp-range=${DHCP_START},${DHCP_END},255.255.255.0,12h
dhcp-option=3,${SERVER_IP}
dhcp-option=6,${SERVER_IP}
# Captive portal : toute requête DNS répond avec l'IP du serveur
address=/#/${SERVER_IP}
EOF

info "hostapd et dnsmasq configurés"

# ── 7. Service hostapd dédié ──────────────────────────────────────────────────
step "Service systemd bazaar-hotspot"

cat > /etc/systemd/system/bazaar-hotspot.service <<EOF
[Unit]
Description=Bazaar WiFi Hotspot
Before=bazaar.service
Wants=network.target
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes

ExecStart=/bin/bash -c '\
    ip link set ${WIFI_IFACE} up && \
    ip addr flush dev ${WIFI_IFACE} && \
    ip addr add ${SERVER_IP}/24 dev ${WIFI_IFACE}'
ExecStop=/bin/bash -c 'ip addr flush dev ${WIFI_IFACE}'

[Install]
WantedBy=multi-user.target
EOF

# hostapd et dnsmasq : on les laisse gérer leurs propres services
systemctl unmask hostapd 2>/dev/null || true
systemctl enable hostapd
systemctl enable dnsmasq
systemctl enable bazaar-hotspot
info "Services hotspot activés"

# ── 8. Service application ────────────────────────────────────────────────────
step "Service systemd bazaar"

cat > /etc/systemd/system/bazaar.service <<EOF
[Unit]
Description=Bazaar Restaurant System
After=network.target bazaar-hotspot.service
Wants=bazaar-hotspot.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bazaar
info "Service bazaar activé"

# ── 9. Démarrage immédiat ─────────────────────────────────────────────────────
step "Démarrage des services"

# Appliquer l'IP maintenant sans attendre le reboot
ip link set "$WIFI_IFACE" up 2>/dev/null || true
ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true
ip addr add "${SERVER_IP}/24" dev "$WIFI_IFACE" 2>/dev/null || true

systemctl restart hostapd
systemctl restart dnsmasq
systemctl restart bazaar

info "Services démarrés"

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installation terminée avec succès   ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
echo -e "  WiFi SSID     : ${YELLOW}${SSID}${NC}"
echo -e "  Mot de passe  : ${YELLOW}${PASSPHRASE}${NC}"
echo -e "  URL tablette  : ${YELLOW}http://${SERVER_IP}:8000${NC}"
echo ""
echo -e "  Commandes utiles :"
echo -e "    journalctl -u bazaar -f       # logs application"
echo -e "    systemctl status bazaar        # statut"
echo -e "    systemctl restart bazaar        # redémarrer"
echo ""
echo -e "  ${YELLOW}Au prochain démarrage, tout sera actif automatiquement.${NC}"
echo ""
