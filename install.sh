#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
#  Bazaar — Script d'installation complet
#  À exécuter une seule fois en root sur la machine cible (Raspberry Pi ou PC).
#  Usage : sudo bash install.sh
# ═══════════════════════════════════════════════════════════════════════════════

INSTALL_DIR="/opt/bazaar"
SERVICE_USER="bazaar"
SSID="${SSID:-Bazaar2026}"
PASSPHRASE="${PASSPHRASE:-bazaar2026}"
SERVER_IP="192.168.50.1"
DHCP_START="192.168.50.10"
DHCP_END="192.168.50.50"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
step()  { echo -e "\n${YELLOW}══ $* ══${NC}"; }

[ "$(id -u)" -eq 0 ] || error "Ce script doit être exécuté en root (sudo bash install.sh)"

# ── Détection de l'interface WiFi ────────────────────────────────────────────
# Priorité : variable d'env WIFI_IFACE > première interface sans-fil détectée
if [ -z "${WIFI_IFACE:-}" ]; then
    WIFI_IFACE="$(find /sys/class/net/*/wireless -maxdepth 0 2>/dev/null \
                  | head -1 | cut -d/ -f5 || true)"
fi

if [ -z "${WIFI_IFACE:-}" ]; then
    warn "Aucune interface WiFi détectée."
    warn "Le hotspot sera ignoré. Connectez un dongle WiFi et relancez install.sh"
    warn "ou forcez l'interface : WIFI_IFACE=wlan0 sudo bash install.sh"
    SKIP_HOTSPOT=1
else
    SKIP_HOTSPOT=0
    info "Interface WiFi détectée : $WIFI_IFACE"
fi

# ── 1. Dépendances système ────────────────────────────────────────────────────
step "Installation des dépendances système"

apt-get update -q
apt-get install -y \
    python3 python3-pip python3-venv \
    hostapd dnsmasq \
    libusb-1.0-0 \
    rfkill
info "Dépendances installées"

rfkill unblock wifi 2>/dev/null || true

# ── 2. Boot rapide — réseau optionnel ────────────────────────────────────────
step "Optimisation du démarrage réseau"

# Marquer les interfaces ethernet/vlan comme optionnelles dans netplan :
# si le câble n'est pas branché le boot ne bloque pas 2 min en attendant
# un DHCP qui ne répond pas.
# On écrit un fichier d'overlay séparé pour ne pas toucher à la config existante.
NETPLAN_OVERLAY="/etc/netplan/60-bazaar-optional.yaml"
# Détecter les interfaces ethernet et vlan configurées dans netplan
ETH_IFACE="$(ip -o link show | awk -F': ' '$2 !~ /lo|docker|br-|veth|wl/ && $3 ~ /ether/ {print $2; exit}')"

cat > "$NETPLAN_OVERLAY" <<EOF
# Généré par install.sh — marque les interfaces comme optionnelles
# pour ne pas bloquer le boot si le réseau est absent.
network:
  version: 2
  ethernets:
$([ -n "$ETH_IFACE" ] && printf "    %s:\n      optional: true\n" "$ETH_IFACE" || true)
  vlans:
    vlan-lab:
      id: 1022
      link: ${ETH_IFACE:-eno1}
      optional: true
EOF

netplan apply 2>/dev/null || true

# Filet de sécurité : limiter le timeout wait-online à 10s
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online --timeout=10
EOF
systemctl daemon-reload
info "Interfaces réseau marquées optionnelles, timeout boot = 10s"

# ── 3. Utilisateur système ────────────────────────────────────────────────────
step "Création de l'utilisateur système"

if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    info "Utilisateur '$SERVICE_USER' créé"
else
    info "Utilisateur '$SERVICE_USER' déjà existant"
fi

# ── 4. Déploiement des fichiers ───────────────────────────────────────────────
step "Déploiement dans $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"
rsync -a --exclude='venv/' --exclude='bazaar.db' "$SCRIPT_DIR/" "$INSTALL_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
info "Fichiers copiés"

# ── 5. Environnement Python ───────────────────────────────────────────────────
step "Création du virtualenv Python"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"
info "Virtualenv prêt"

# ── 6. Règles udev pour les imprimantes USB ───────────────────────────────────
step "Règles udev imprimantes USB"

cat > /etc/udev/rules.d/99-bazaar-printers.rules <<'EOF'
# Imprimantes thermiques — accès pour l'utilisateur bazaar
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", GROUP="bazaar", MODE="0660"
SUBSYSTEM=="usb", ENV{ID_USB_INTERFACES}=="*:07*", GROUP="bazaar", MODE="0660"
EOF

usermod -aG plugdev "$SERVICE_USER" 2>/dev/null || true
udevadm control --reload-rules
udevadm trigger
info "Règles udev installées"

# ── 7. Hotspot WiFi ───────────────────────────────────────────────────────────
if [ "$SKIP_HOTSPOT" -eq 0 ]; then
    step "Configuration du hotspot WiFi ($WIFI_IFACE)"

    # Empêcher NetworkManager de gérer cette interface
    if command -v nmcli &>/dev/null; then
        nmcli device set "$WIFI_IFACE" managed no 2>/dev/null || true
        mkdir -p /etc/NetworkManager/conf.d
        cat > /etc/NetworkManager/conf.d/bazaar-wifi.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${WIFI_IFACE}
EOF
        info "NetworkManager : $WIFI_IFACE marqué unmanaged"
    fi

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
address=/#/${SERVER_IP}
EOF

    info "hostapd et dnsmasq configurés"

    # Service bazaar-hotspot : monte l'IP sur l'interface
    cat > /etc/systemd/system/bazaar-hotspot.service <<EOF
[Unit]
Description=Bazaar WiFi Hotspot
Before=bazaar.service hostapd.service
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c '\
    ip link set ${WIFI_IFACE} up && \
    ip addr flush dev ${WIFI_IFACE} && \
    ip addr add ${SERVER_IP}/24 dev ${WIFI_IFACE} && \
    iptables -t nat -C PREROUTING -i ${WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 8000 2>/dev/null || \
    iptables -t nat -A PREROUTING -i ${WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 8000'
ExecStop=/bin/bash -c '\
    ip addr flush dev ${WIFI_IFACE} ; \
    iptables -t nat -D PREROUTING -i ${WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 8000 2>/dev/null || true'

[Install]
WantedBy=multi-user.target
EOF

    # Drop-in hostapd : démarre après bazaar-hotspot (interface déjà montée)
    mkdir -p /etc/systemd/system/hostapd.service.d
    cat > /etc/systemd/system/hostapd.service.d/bazaar.conf <<EOF
[Unit]
After=bazaar-hotspot.service
Requires=bazaar-hotspot.service
EOF

    systemctl unmask hostapd 2>/dev/null || true
    systemctl enable hostapd
    systemctl enable dnsmasq
    systemctl enable bazaar-hotspot
    info "Services hotspot activés"
else
    step "Hotspot ignoré (pas d'interface WiFi)"
fi

# ── 8. Service application ────────────────────────────────────────────────────
step "Service systemd bazaar"

if [ "$SKIP_HOTSPOT" -eq 0 ]; then
    AFTER_LINE="After=network.target bazaar-hotspot.service"
    WANTS_LINE="Wants=bazaar-hotspot.service"
else
    AFTER_LINE="After=network.target"
    WANTS_LINE=""
fi

cat > /etc/systemd/system/bazaar.service <<EOF
[Unit]
Description=Bazaar Restaurant System
${AFTER_LINE}
${WANTS_LINE}
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

if [ "$SKIP_HOTSPOT" -eq 0 ]; then
    ip link set "$WIFI_IFACE" up 2>/dev/null || true
    ip addr flush dev "$WIFI_IFACE" 2>/dev/null || true
    ip addr add "${SERVER_IP}/24" dev "$WIFI_IFACE" 2>/dev/null || true
    systemctl restart hostapd
    systemctl restart dnsmasq
fi

systemctl restart bazaar
info "Services démarrés"

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installation terminée avec succès   ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""
if [ "$SKIP_HOTSPOT" -eq 0 ]; then
    echo -e "  WiFi SSID     : ${YELLOW}${SSID}${NC}"
    echo -e "  Mot de passe  : ${YELLOW}${PASSPHRASE}${NC}"
    echo -e "  URL tablette  : ${YELLOW}http://${SERVER_IP}:8000${NC}"
else
    warn "Hotspot non configuré — connectez un dongle WiFi et relancez install.sh"
    echo -e "  URL locale    : ${YELLOW}http://$(hostname -I | awk '{print $1}'):8000${NC}"
fi
echo ""
echo -e "  Commandes utiles :"
echo -e "    journalctl -u bazaar -f        # logs application"
echo -e "    systemctl status bazaar         # statut"
echo -e "    systemctl restart bazaar        # redémarrer"
echo ""
echo -e "  ${YELLOW}Au prochain démarrage, tout sera actif automatiquement.${NC}"
echo ""
