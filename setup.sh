#!/bin/bash
# Habit Tracker ePaper Display - Raspberry Pi Setup Script
#
# Idempotent: safe to run multiple times (e.g. after git pull).
#
# Usage:
#   sudo ./setup.sh           # Full setup
#   sudo ./setup.sh --skip-apt  # Skip apt update (faster reruns)

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "\n${BOLD}── $1 ──${NC}"; }

# ── Pre-flight checks ───────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "Please run as root: sudo ./setup.sh"
    exit 1
fi

SKIP_APT=false
for arg in "$@"; do
    case "$arg" in
        --skip-apt) SKIP_APT=true ;;
    esac
done

ACTUAL_USER="${SUDO_USER:-pi}"
ACTUAL_HOME=$(eval echo "~${ACTUAL_USER}")
INSTALL_DIR="${ACTUAL_HOME}/habit-tracker-epaper"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEEDS_REBOOT=false

info "Habit Tracker ePaper Display — Setup"
info "User: ${ACTUAL_USER} | Install dir: ${INSTALL_DIR}"

# ── 1. System packages ──────────────────────────────────────
step "System packages"

if [ "$SKIP_APT" = true ]; then
    info "Skipping apt update (--skip-apt)"
else
    info "Updating package lists..."
    apt-get update -qq
fi

PACKAGES=(
    python3
    python3-pip
    python3-venv
    python3-dev
    python3-lgpio      # GPIO backend for gpiozero (prebuilt for Pi)
    libopenjp2-7
    libtiff6
    libopenblas-dev
    git
)

# Only install what's missing
MISSING=()
for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    info "Installing: ${MISSING[*]}"
    apt-get install -y -qq "${MISSING[@]}"
else
    info "All system packages already installed"
fi

# ── 2. Enable SPI ────────────────────────────────────────────
step "SPI interface"

# Determine which config.txt to use
BOOT_CONFIG=""
for path in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$path" ]; then
        BOOT_CONFIG="$path"
        break
    fi
done

if [ -n "$BOOT_CONFIG" ]; then
    if grep -q "^dtparam=spi=on" "$BOOT_CONFIG"; then
        info "SPI already enabled in ${BOOT_CONFIG}"
    else
        info "Enabling SPI in ${BOOT_CONFIG}"
        echo "dtparam=spi=on" >> "$BOOT_CONFIG"
        NEEDS_REBOOT=true
    fi
else
    warn "Could not find boot config — enable SPI manually via raspi-config"
fi

# Verify SPI is actually active (won't be until after reboot if just enabled)
if ls /dev/spidev* &>/dev/null; then
    info "SPI devices present: $(ls /dev/spidev* 2>/dev/null | tr '\n' ' ')"
else
    warn "No SPI devices found — a reboot may be required"
    NEEDS_REBOOT=true
fi

# ── 3. Copy project files (if running from outside install dir) ──
step "Project files"

if [ "${SCRIPT_DIR}" != "${INSTALL_DIR}" ]; then
    info "Copying project to ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}"
    rsync -a --exclude='.venv' --exclude='.git' "${SCRIPT_DIR}/" "${INSTALL_DIR}/"
    chown -R "${ACTUAL_USER}:${ACTUAL_USER}" "${INSTALL_DIR}"
else
    info "Already running from install directory"
fi

# ── 4. Python virtual environment ────────────────────────────
step "Python virtual environment"

# Use --system-site-packages so the venv can access system-installed
# GPIO libraries (python3-lgpio) which are difficult to build from source.
if [ -d "${INSTALL_DIR}/.venv" ] && [ -f "${INSTALL_DIR}/.venv/bin/python" ]; then
    info "Virtual environment already exists"
else
    info "Creating virtual environment (with system site-packages)..."
    sudo -u "${ACTUAL_USER}" python3 -m venv --system-site-packages "${INSTALL_DIR}/.venv"
fi

info "Upgrading pip..."
sudo -u "${ACTUAL_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip -q

info "Installing Python dependencies..."
sudo -u "${ACTUAL_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q

# ── 5. Configuration file ────────────────────────────────────
step "Configuration"

if [ -f "${INSTALL_DIR}/config.yaml" ]; then
    info "config.yaml found"
else
    warn "config.yaml not found!"
    echo ""
    echo "  You have two options:"
    echo ""
    echo "  Option A — Copy from your Mac:"
    echo "    scp config.yaml ${ACTUAL_USER}@$(hostname).local:${INSTALL_DIR}/config.yaml"
    echo ""
    echo "  Option B — Create from template:"
    echo "    cp ${INSTALL_DIR}/config.example.yaml ${INSTALL_DIR}/config.yaml"
    echo "    nano ${INSTALL_DIR}/config.yaml"
    echo ""
fi

# ── 6. Systemd service + timer ──────────────────────────────
step "Systemd service & timer"

# Generate the service file with correct paths/user (don't rely on sed-in-place)
cat > /etc/systemd/system/habit-tracker.service <<EOF
[Unit]
Description=Habit Tracker ePaper Display Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${ACTUAL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m src.main
Environment=PYTHONUNBUFFERED=1

# Logging
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=256M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

cp "${INSTALL_DIR}/habit-tracker.timer" /etc/systemd/system/habit-tracker.timer

systemctl daemon-reload
systemctl enable habit-tracker.timer

info "Systemd timer enabled (will start on next boot)"

# ── 7. Smoke test ────────────────────────────────────────────
step "Smoke test"

info "Running import check..."
# Don't import waveshare here — it claims GPIO pins at import time,
# which fails if another process (e.g. the timer) is using them.
if sudo -u "${ACTUAL_USER}" bash -c "cd ${INSTALL_DIR} && .venv/bin/python -c \"
from src.config import load_config
from src.renderer import HabitRenderer
from src.notion_service import NotionService
print('All imports OK')
\"" 2>&1; then
    info "Import check passed"
else
    warn "Import check failed — see errors above"
fi

if [ -f "${INSTALL_DIR}/config.yaml" ]; then
    info "Running demo render..."
    if sudo -u "${ACTUAL_USER}" bash -c "cd ${INSTALL_DIR} && .venv/bin/python -m src.main --demo --preview --output /tmp/habit-tracker-test.png" 2>&1; then
        info "Demo render succeeded -> /tmp/habit-tracker-test.png"
    else
        warn "Demo render failed — see errors above"
    fi
fi

# ── Summary ──────────────────────────────────────────────────
step "Done"

echo ""
info "Setup complete!"
echo ""

if [ "$NEEDS_REBOOT" = true ]; then
    warn "Reboot required for SPI changes: sudo reboot"
    echo ""
fi

if [ ! -f "${INSTALL_DIR}/config.yaml" ]; then
    warn "Still need to set up config.yaml (see above)"
    echo ""
fi

echo "Quick reference:"
echo "  Test (demo):    cd ${INSTALL_DIR} && .venv/bin/python -m src.main --demo"
echo "  Test (Notion):  cd ${INSTALL_DIR} && .venv/bin/python -m src.main"
echo "  Start timer:    sudo systemctl start habit-tracker.timer"
echo "  Check timer:    systemctl status habit-tracker.timer"
echo "  View logs:      journalctl -u habit-tracker.service -n 20"
echo "  Rerun setup:    cd ${INSTALL_DIR} && git pull && sudo ./setup.sh --skip-apt"
echo ""
