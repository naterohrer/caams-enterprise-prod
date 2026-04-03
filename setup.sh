#!/usr/bin/env bash
# setup.sh — CAAMS Docker Compose setup (idempotent, non-root friendly)
#
# Automatically:
#   1. Checks Docker is installed and reachable by the current user
#   2. Checks whether the user is in the 'docker' group (and explains the fix if not)
#   3. Creates a .env file with secure random secrets (skipped if one already exists)
#   4. Builds images and starts the stack
#   5. Applies the database schema (alembic upgrade head)
#   6. Seeds frameworks and tool catalog (safe to re-run)
#
# Usage:
#   bash setup.sh

set -euo pipefail

# ── Helpers ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${BLUE}──${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Detect Docker ───────────────────────────────────────────────────────────

step "Checking prerequisites…"

if ! command -v docker &>/dev/null; then
  error "Docker is not installed.\n  Install it from: https://docs.docker.com/get-docker/\n  Then re-run: bash setup.sh"
fi

# Prefer Compose v2 plugin. Fall back to v1 only when the Docker Engine is old
# enough to be compatible (< 25.x). v1 crashes with KeyError: 'ContainerConfig'
# against Docker Engine ≥ 25.x.
if docker compose version &>/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_V1_VER="$(docker-compose --version 2>/dev/null || true)"
  # Extract Docker Engine major version (e.g. "27" from "Docker version 27.0.3, …")
  DOCKER_MAJOR="$(docker --version 2>/dev/null | grep -oP '(?<=version )\d+' | head -1 || echo 0)"
  if [[ "${DOCKER_MAJOR}" -ge 25 ]]; then
    echo ""
    echo -e "${RED}[✗]${NC} docker-compose v1 is installed (${COMPOSE_V1_VER}) but is not compatible"
    echo "     with Docker Engine ≥ 25.x (crashes with KeyError: 'ContainerConfig')."
    echo ""
    echo "  Install Docker Compose v2 with one of:"
    echo ""
    echo "    # Option A — Docker APT package (Ubuntu/Debian)"
    echo "    sudo apt-get update && sudo apt-get install -y docker-compose-plugin"
    echo ""
    echo "    # Option B — manual binary install"
    echo "    ARCH=\$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/aarch64/')"
    echo "    sudo mkdir -p /usr/local/lib/docker/cli-plugins"
    echo "    sudo curl -SL \"https://github.com/docker/compose/releases/latest/download/docker-compose-linux-\${ARCH}\" \\"
    echo "         -o /usr/local/lib/docker/cli-plugins/docker-compose"
    echo "    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose"
    echo ""
    echo "  After installing, re-run: bash setup.sh"
    echo ""
    exit 1
  else
    warn "Using docker-compose v1 (${COMPOSE_V1_VER}) — compatible with this Docker Engine version."
    COMPOSE="docker-compose"
  fi
else
  error "Docker Compose not found.\n  Install it from: https://docs.docker.com/compose/install/\n  Then re-run: bash setup.sh"
fi

info "Docker:  $(docker --version)"
info "Compose: $($COMPOSE version --short 2>/dev/null || $COMPOSE version)"

# ── 2. Check Docker daemon access ─────────────────────────────────────────────

step "Checking Docker daemon access…"

if ! docker info &>/dev/null 2>&1; then
  echo ""
  if [[ $EUID -eq 0 ]]; then
    echo "  Cannot connect to the Docker daemon even as root."
    echo "  Is Docker running?  Try: systemctl start docker"
  else
    echo "  Cannot connect to the Docker daemon."
    echo "  Your user '$(whoami)' may not be in the 'docker' group."
    echo ""
    echo "  Fix it with:"
    echo ""
    echo "    sudo usermod -aG docker $(whoami)"
    echo "    newgrp docker        # applies immediately without logging out"
    echo ""
    echo "  Or log out and back in, then re-run: bash setup.sh"
  fi
  echo ""
  exit 1
fi

# Warn (but don't abort) if running as root — it works but isn't recommended.
if [[ $EUID -eq 0 ]]; then
  warn "Running as root. This works but is not recommended for production."
else
  # Check whether the user is explicitly in the docker group.
  # (They passed the docker info check above, so they do have access, but the
  #  group membership check is informational for ops/audit purposes.)
  if ! id -nG "$(whoami)" | grep -qw docker; then
    warn "'$(whoami)' is not in the 'docker' group, but can still reach the daemon."
    warn "If Docker access stops working after a reboot, run: sudo usermod -aG docker $(whoami)"
  else
    info "User '$(whoami)' is in the 'docker' group — OK"
  fi
fi

info "Docker daemon: accessible"

# ── 3. Generate secrets helper ────────────────────────────────────────────────
# Prefer python3 (most reliable); fall back to openssl; last resort: /dev/urandom.

_hex() {
  local bytes=$1
  if command -v python3 &>/dev/null; then
    python3 -c "import secrets; print(secrets.token_hex($bytes))"
  elif command -v openssl &>/dev/null; then
    openssl rand -hex "$bytes"
  else
    # POSIX fallback — available on any Linux/macOS with /dev/urandom
    od -A n -t x1 -N "$bytes" /dev/urandom | tr -d ' \n'
  fi
}

_urlsafe() {
  local bytes=$1
  if command -v python3 &>/dev/null; then
    python3 -c "import secrets; print(secrets.token_urlsafe($bytes))"
  elif command -v openssl &>/dev/null; then
    openssl rand -base64 "$bytes" | tr '+/' '-_' | tr -d '='
  else
    od -A n -t x1 -N "$bytes" /dev/urandom | tr -d ' \n'
  fi
}

# ── 4. Create .env if missing ─────────────────────────────────────────────────

step "Checking environment file…"

ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  warn ".env already exists — leaving it unchanged."
  warn "Delete $ENV_FILE and re-run to generate fresh secrets."
else
  info "Generating .env with secure random secrets…"

  SECRET_KEY="$(_hex 32)"
  DB_PASSWORD="$(_urlsafe 24)"

  cat > "$ENV_FILE" <<EOF
# CAAMS runtime environment — generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Keep this file private. Do not commit it to version control.

# JWT signing key (required — change this if you regenerate)
CAAMS_SECRET_KEY=${SECRET_KEY}

# PostgreSQL password (used by both the app and the database container)
DB_PASSWORD=${DB_PASSWORD}

# Optional: set your server's base URL for invite email links
# CAAMS_APP_BASE_URL=https://caams.example.com

# Optional: enable Swagger UI at /docs (not recommended in production)
# CAAMS_ENABLE_DOCS=false
EOF

  chmod 600 "$ENV_FILE"
  info ".env created (permissions set to 600)"
  info "Secrets were randomly generated — no manual steps needed."
fi

# ── 5. Build and start the stack ──────────────────────────────────────────────

step "Building images and starting containers…"

cd "$SCRIPT_DIR"
$COMPOSE up -d --build

# ── 6. Wait for CAAMS to become healthy ───────────────────────────────────────

step "Waiting for CAAMS to become ready…"

MAX_WAIT=120  # seconds
INTERVAL=3
elapsed=0

printf "  Waiting"
while true; do
  # Health-check inside the container avoids a host dependency on curl/wget.
  if $COMPOSE exec -T caams \
      python3 -c \
      "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=3); sys.exit(0)" \
      &>/dev/null 2>&1; then
    echo ""
    info "CAAMS is up and responding"
    break
  fi

  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo ""
    error "CAAMS did not become ready within ${MAX_WAIT}s.\n  Check logs with: $COMPOSE logs caams"
  fi

  printf "."
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

# ── 7. Apply schema migrations ────────────────────────────────────────────────

step "Applying database schema (alembic upgrade head)…"
$COMPOSE exec -T caams alembic upgrade head
info "Schema is up to date"

# ── 8. Seed frameworks and tool catalog ───────────────────────────────────────

step "Seeding frameworks and tool catalog…"
$COMPOSE exec -T caams python seed.py
info "Seed complete (safe to re-run at any time)"

# ── Done ──────────────────────────────────────────────────────────────────────

LOCAL_URL="http://localhost:8000"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   CAAMS is ready!                             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Open: $LOCAL_URL"
echo ""
echo "  First visit? You'll be prompted to create the initial admin account."
echo ""
echo "  Useful commands:"
printf "    %-38s %s\n" "$COMPOSE logs -f"    "# stream live logs"
printf "    %-38s %s\n" "$COMPOSE ps"         "# check container status"
printf "    %-38s %s\n" "$COMPOSE down"       "# stop everything"
printf "    %-38s %s\n" "$COMPOSE down -v"    "# stop and erase all data (destructive)"
echo ""
