#!/bin/bash
# Container initialization script for ailab
# Run inside the container as root to set up the environment
set -euo pipefail

USERNAME="$1"
USER_UID="$2"
USER_GID="$3"
USER_HOME="$4"

log() { echo "[ailab] $*"; }

log "Initializing container for user $USERNAME (uid=$USER_UID, gid=$USER_GID)"

# ── Base packages ──────────────────────────────────────────────────────────────
log "Updating apt and installing base packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    pipx \
    git \
    curl \
    wget \
    build-essential \
    ca-certificates \
    gnupg \
    sudo \
    bash-completion \
    locales \
    unzip \
    zip \
    jq \
    htop \
    vim \
    nano \
    file \
    lsb-release \
    xdg-utils \
    socat \
    netcat-openbsd \
    dbus-user-session \
    systemd-container

# ── Locale ─────────────────────────────────────────────────────────────────────
log "Setting up locale..."
locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8

# ── Node.js via NodeSource ─────────────────────────────────────────────────────
log "Installing Node.js LTS..."
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt-get install -y -q nodejs
npm install -g npm@latest

# ── User setup ─────────────────────────────────────────────────────────────────
log "Setting up user $USERNAME (uid=$USER_UID, gid=$USER_GID)..."

# If a group with GID already exists under a different name, rename it.
EXISTING_GROUP=$(getent group "$USER_GID" | cut -d: -f1)
if [ -n "$EXISTING_GROUP" ] && [ "$EXISTING_GROUP" != "$USERNAME" ]; then
    log "Renaming existing group '$EXISTING_GROUP' (gid=$USER_GID) to '$USERNAME'"
    groupmod -n "$USERNAME" "$EXISTING_GROUP"
elif [ -z "$EXISTING_GROUP" ]; then
    groupadd -g "$USER_GID" "$USERNAME"
fi

# If a user with UID already exists under a different name, rename it.
EXISTING_USER=$(getent passwd "$USER_UID" | cut -d: -f1)
if [ -n "$EXISTING_USER" ] && [ "$EXISTING_USER" != "$USERNAME" ]; then
    log "Renaming existing user '$EXISTING_USER' (uid=$USER_UID) to '$USERNAME'"
    usermod -l "$USERNAME" -d "$USER_HOME" -s /bin/bash "$EXISTING_USER"
elif [ -z "$EXISTING_USER" ]; then
    useradd \
        --uid "$USER_UID" \
        --gid "$USER_GID" \
        --shell /bin/bash \
        --no-create-home \
        --home-dir "$USER_HOME" \
        "$USERNAME"
fi

# Passwordless sudo
echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}"
chmod 0440 "/etc/sudoers.d/${USERNAME}"

# Enable persistent user systemd session so apps can install user services
loginctl enable-linger "$USERNAME" || log "Warning: loginctl enable-linger failed (non-fatal)"

# Start the user's systemd session now (creates /run/user/$UID and D-Bus socket)
systemctl start "user@${USER_UID}.service" || log "Warning: could not start user session (non-fatal)"

# ── Bun ────────────────────────────────────────────────────────────────────────
log "Installing Bun..."
sudo -u "$USERNAME" bash -c \
    'curl -fsSL https://bun.sh/install | bash' \
    || log "Warning: Bun install failed (non-fatal)"

# ── Homebrew (Linuxbrew) ───────────────────────────────────────────────────────
log "Installing Homebrew..."
sudo -u "$USERNAME" bash -c \
    'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' \
    || log "Warning: Homebrew install failed (non-fatal)"

# ── Profile / bashrc setup ────────────────────────────────────────────────────
log "Writing shell profile additions..."
PROFILE_SNIPPET="/etc/profile.d/ailab.sh"
cat > "$PROFILE_SNIPPET" <<'PROFILE'
# ailab environment
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Homebrew
if [ -d "/home/linuxbrew/.linuxbrew" ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi

# Bun
if [ -d "$HOME/.bun" ]; then
    export BUN_INSTALL="$HOME/.bun"
    export PATH="$BUN_INSTALL/bin:$PATH"
fi

# pipx
export PATH="$PATH:$HOME/.local/bin"

# lemonade / ollama already at localhost - no override needed (proxy handles it)
PROFILE

log "Container initialization complete!"
log "User $USERNAME is ready inside the container."
