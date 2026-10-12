#!/usr/bin/env bash
# ============================================================================
#  netlab installer -- Ubuntu networking / iptables / Kubernetes practice lab
#
#  Usage:
#    sudo ./install.sh                 install netlab + dependencies
#    sudo ./install.sh --with-k8s      also install k3s and seed the cluster
#    sudo ./install.sh --deps-only     just install the apt packages
#    sudo ./install.sh --uninstall     remove netlab (leaves k3s alone)
#    sudo ./install.sh --prefix /opt   change the install prefix
#
#  Tested on Ubuntu 22.04 and 24.04. Should work on any Debian derivative.
# ============================================================================
set -euo pipefail

PREFIX="/opt"
DEST=""
WITH_K8S=0
DEPS_ONLY=0
UNINSTALL=0
NO_APT=0

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -t 1 ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
  R=''; G=''; Y=''; B=''; N=''
fi
info() { printf '%s[*]%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '%s[+]%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s[!]%s %s\n' "$Y" "$N" "$*" >&2; }
die()  { printf '%s[x]%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --with-k8s)  WITH_K8S=1 ;;
    --deps-only) DEPS_ONLY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-apt)    NO_APT=1 ;;
    --prefix)    shift; PREFIX="${1:?--prefix needs a path}" ;;
    -h|--help)   sed -n '2,15p' "$0"; exit 0 ;;
    *) die "Unknown option: $1  (try --help)" ;;
  esac
  shift
done

DEST="$PREFIX/netlab"

[ "$(id -u)" -eq 0 ] || die "Run me with sudo:  sudo ./install.sh"

# ---------------------------------------------------------------- uninstall --
if [ "$UNINSTALL" = "1" ]; then
  info "Tearing down any running lab..."
  [ -x "$DEST/bin/netlab" ] && "$DEST/bin/netlab" lab down >/dev/null 2>&1 || true
  rm -f /usr/local/bin/netlab
  rm -rf "$DEST"
  rm -rf /var/lib/netlab /run/netlab /srv/netlab-www
  ok "netlab removed. State and snapshots are gone too."
  warn "k3s was NOT removed. To remove it: sudo /usr/local/bin/k3s-uninstall.sh"
  exit 0
fi

# ------------------------------------------------------------- sanity check --
if [ -r /etc/os-release ]; then
  . /etc/os-release
  case "${ID:-}${ID_LIKE:-}" in
    *debian*|*ubuntu*) : ;;
    *) warn "This installer targets Ubuntu/Debian. Detected: ${PRETTY_NAME:-unknown}"
       warn "Package installation may fail. Re-run with --no-apt to skip it." ;;
  esac
fi

if ! [ -e /proc/sys/net/ipv4/ip_forward ]; then
  die "This does not look like a Linux host with a normal network stack.
     netlab must run INSIDE an Ubuntu VM, not on Windows or macOS.
     (WSL2 works for most drills; a real VM works for all of them.)"
fi

# ------------------------------------------------------------- dependencies --
PKGS=(
  iproute2 iptables iputils-ping iputils-arping traceroute tcpdump
  curl wget dnsutils netcat-openbsd socat conntrack ethtool
  python3 jq less bash-completion ipcalc mtr-tiny nftables
)

install_deps() {
  if [ "$NO_APT" = "1" ]; then
    warn "Skipping apt (--no-apt). Make sure these exist: ${PKGS[*]}"
    return 0
  fi
  info "Installing dependencies (this may take a minute)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || warn "apt-get update failed; continuing with the cache"
  # Install individually so one unavailable package does not abort everything.
  local p failed=()
  for p in "${PKGS[@]}"; do
    apt-get install -y -qq --no-install-recommends "$p" >/dev/null 2>&1 || failed+=("$p")
  done
  if [ "${#failed[@]}" -gt 0 ]; then
    warn "Could not install: ${failed[*]}"
    warn "Most drills will still work. Install them by hand if a command is missing."
  fi
  ok "Dependencies installed."
}

install_deps
[ "$DEPS_ONLY" = "1" ] && { ok "Done (--deps-only)."; exit 0; }

# ------------------------------------------------------------------ install --
info "Installing netlab to $DEST ..."
mkdir -p "$DEST"
# Copy everything except VCS noise; preserve nothing from a previous install.
rm -rf "$DEST/bin" "$DEST/lib" "$DEST/drills" "$DEST/guides" "$DEST/k8s" "$DEST/extras"
cp -r "$SRC_DIR/bin" "$SRC_DIR/lib" "$SRC_DIR/drills" "$SRC_DIR/guides" \
      "$SRC_DIR/k8s" "$DEST/"
if [ -d "$SRC_DIR/extras" ]; then cp -r "$SRC_DIR/extras" "$DEST/"; fi
cp "$SRC_DIR/VERSION" "$SRC_DIR/README.md" "$DEST/" 2>/dev/null || true

# Strip CRLF in case the package travelled through Windows, then set modes.
info "Normalising line endings and permissions..."
find "$DEST" -type f \( -name '*.sh' -o -name 'netlab' -o -name '*.yaml' \
     -o -name '*.md' -o -name '*.txt' \) -print0 \
  | xargs -0 -r sed -i 's/\r$//'
chmod +x "$DEST/bin/netlab"
chmod 644 "$DEST"/lib/*.sh "$DEST"/drills/*.sh 2>/dev/null || true

ln -sf "$DEST/bin/netlab" /usr/local/bin/netlab
mkdir -p /var/lib/netlab /run/netlab /srv/netlab-www
touch /var/log/netlab.log

# Make "sudo netlab" work even with a sanitised secure_path.
if ! sudo -l 2>/dev/null | grep -q '/usr/local/bin'; then
  warn "/usr/local/bin may not be in sudo secure_path. If 'sudo netlab' is not"
  warn "found, use the full path: sudo $DEST/bin/netlab"
fi

# Shell completion (best effort).
if [ -d /etc/bash_completion.d ]; then
  cat > /etc/bash_completion.d/netlab <<'COMPEOF'
_netlab() {
  local cur prev cmds
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  cmds="lab list start challenge reveal check hint solution reset status progress exec sh guide doctor snapshot deadman deadman-cancel k8s version help"
  case "$prev" in
    start|check|hint|solution|reset)
      COMPREPLY=($(compgen -W "$(ls __NETLAB_DEST__/drills 2>/dev/null | sed 's/\.sh$//')" -- "$cur")); return;;
    exec|sh) COMPREPLY=($(compgen -W "client router server" -- "$cur")); return;;
    lab)     COMPREPLY=($(compgen -W "up down rebuild map" -- "$cur")); return;;
    k8s)     COMPREPLY=($(compgen -W "up down status reset iptables" -- "$cur")); return;;
    challenge) COMPREPLY=($(compgen -W "net fw k8s" -- "$cur")); return;;
  esac
  COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
}
complete -F _netlab netlab
COMPEOF
  sed -i "s|__NETLAB_DEST__|$DEST|g" /etc/bash_completion.d/netlab
  ok "Bash completion installed (new shells, or: source /etc/bash_completion.d/netlab)"
fi

ok "netlab installed."

# --------------------------------------------------------------- kubernetes --
if [ "$WITH_K8S" = "1" ]; then
  info "Installing Kubernetes (k3s)..."
  "$DEST/bin/netlab" k8s up || warn "k3s install did not complete. Run 'sudo netlab k8s up' later."
fi

# ------------------------------------------------------------------- finish --
cat <<'DONEEOF'

==============================================================================
  netlab is installed.
==============================================================================

  Next steps:

    netlab doctor                 check this machine has everything
    netlab guide 00               read the orientation guide (start here)
    sudo netlab lab up            build the network topology
    sudo netlab list              see all the drills
    sudo netlab start net-01-link-down

  For the Kubernetes half:

    sudo netlab k8s up            install k3s and seed the practice namespace
    sudo netlab start k8s-01-first-deployment

  Everything the network drills touch lives inside network namespaces, so
  breaking them cannot take your VM off the network. The two exceptions are
  clearly marked in the drill text.

  Full command reference:  netlab help

DONEEOF
