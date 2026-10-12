#!/usr/bin/env bash
# netlab :: lib/common.sh -- shared constants and helpers
# Sourced by bin/netlab, lib/*.sh and every drill file.

# ---------------------------------------------------------------- paths ----
NETLAB_ROOT="${NETLAB_ROOT:-/opt/netlab}"
NETLAB_STATE_DIR="${NETLAB_STATE_DIR:-/var/lib/netlab}"
NETLAB_RUN_DIR="${NETLAB_RUN_DIR:-/run/netlab}"
NETLAB_LOG="${NETLAB_LOG:-/var/log/netlab.log}"
NETLAB_WWW="${NETLAB_WWW:-/srv/netlab-www}"
PROGRESS_FILE="$NETLAB_STATE_DIR/progress"
ACTIVE_FILE="$NETLAB_STATE_DIR/active"
CHALLENGE_FILE="$NETLAB_STATE_DIR/challenge"

# ------------------------------------------------------------- topology ----
# Three network namespaces wired together, plus an uplink to the host.
#
#   [ HOST ]  10.10.0.1 ---- 10.10.0.2 [ nl-router ] 10.10.1.1 ---- 10.10.1.10 [ nl-client ]
#      nl-up-h                 up0                     lan0             eth0
#                                          10.10.2.1 ---- 10.10.2.10 [ nl-server ]
#                                            dmz0             eth0
#
NS_CLIENT="nl-client"
NS_ROUTER="nl-router"
NS_SERVER="nl-server"
NETLAB_NAMESPACES=("$NS_CLIENT" "$NS_ROUTER" "$NS_SERVER")

UPLINK_NET="10.10.0.0/24"
HOST_UP_IP="10.10.0.1"
ROUTER_UP_IP="10.10.0.2"

LAN_NET="10.10.1.0/24"
ROUTER_LAN_IP="10.10.1.1"
CLIENT_IP="10.10.1.10"

DMZ_NET="10.10.2.0/24"
ROUTER_DMZ_IP="10.10.2.1"
SERVER_IP="10.10.2.10"

LAB_SUPERNET="10.10.0.0/16"

HTTP_PORT="8080"
ALT_PORT="9090"

# Host-side veth name (must be <= 15 chars)
HOST_VETH="nl-up-h"

# Kubernetes lab namespace
K8S_NS="netlab"

# ---------------------------------------------------------------- colors ---
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_MAGENTA=$'\033[35m'; C_CYAN=$'\033[36m'
else
  C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''
  C_YELLOW=''; C_BLUE=''; C_MAGENTA=''; C_CYAN=''
fi

say()  { printf '%s\n' "$*"; }
info() { printf '%s[*]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[+]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%s[x]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
die()  { err "$*"; exit 1; }
hr()   { printf '%s%s%s\n' "$C_DIM" "------------------------------------------------------------------" "$C_RESET"; }
title(){ printf '\n%s%s%s\n' "$C_BOLD$C_CYAN" "$*" "$C_RESET"; hr; }

log() {
  local ts; ts="$(date '+%Y-%m-%d %H:%M:%S')"
  printf '%s %s\n' "$ts" "$*" >> "$NETLAB_LOG" 2>/dev/null || true
}

have()      { command -v "$1" >/dev/null 2>&1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "This command needs root. Re-run with: sudo netlab $*"; }

ensure_dirs() {
  mkdir -p "$NETLAB_STATE_DIR" "$NETLAB_RUN_DIR" "$NETLAB_WWW" 2>/dev/null || true
  touch "$PROGRESS_FILE" 2>/dev/null || true
}

# --------------------------------------------------------- netns helpers ---
# nsx <short-ns-name> <command...>   e.g.  nsx client ip addr show
nsx() {
  local ns="$1"; shift
  ip netns exec "nl-$ns" "$@"
}

# nsq -- quiet variant, returns exit status only
nsq() {
  local ns="$1"; shift
  ip netns exec "nl-$ns" "$@" >/dev/null 2>&1
}

ns_exists() { ip netns list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

topo_is_up() {
  local ns
  for ns in "${NETLAB_NAMESPACES[@]}"; do
    ns_exists "$ns" || return 1
  done
  return 0
}

require_topo() {
  topo_is_up || die "Lab topology is not running. Start it with:  sudo netlab lab up"
}

# ------------------------------------------------------- test primitives ---
# All of these are used by drill_verify() functions. Keep them fast and quiet.

t_ping() { # t_ping <ns> <ip> [count]
  local ns="$1" ip="$2" c="${3:-2}"
  nsq "$ns" ping -c "$c" -W 2 -q "$ip"
}

t_http() { # t_http <ns> <url> [timeout]
  local ns="$1" url="$2" to="${3:-4}"
  nsq "$ns" curl -s -o /dev/null --max-time "$to" "$url"
}

t_tcp() { # t_tcp <ns> <ip> <port> -- TCP connect test without curl
  local ns="$1" ip="$2" port="$3"
  nsq "$ns" timeout 4 bash -c "exec 3<>/dev/tcp/$ip/$port"
}

t_resolves_to() { # t_resolves_to <ns> <name> <expected-ip>
  local ns="$1" name="$2" want="$3" got
  got="$(nsx "$ns" getent hosts "$name" 2>/dev/null | awk '{print $1; exit}')"
  [ "$got" = "$want" ]
}

t_bigfile() { # t_bigfile <ns> <url> -- catches MTU/PMTU black holes
  local ns="$1" url="$2"
  nsq "$ns" curl -s -o /dev/null --max-time 12 "$url"
}

# --------------------------------------------------------------- progress --
progress_get() { # progress_get <id> -> prints "passed" or ""
  [ -f "$PROGRESS_FILE" ] || return 0
  awk -F= -v id="$1" '$1==id {print $2}' "$PROGRESS_FILE" | tail -1
}

progress_set() { # progress_set <id> <state>
  ensure_dirs
  local tmp; tmp="$(mktemp)"
  grep -v "^$1=" "$PROGRESS_FILE" 2>/dev/null > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$PROGRESS_FILE"
}

progress_clear() { : > "$PROGRESS_FILE"; }

active_set()   { ensure_dirs; printf '%s\n' "$1" > "$ACTIVE_FILE"; }
active_get()   { [ -f "$ACTIVE_FILE" ] && cat "$ACTIVE_FILE" || true; }
active_clear() { rm -f "$ACTIVE_FILE" "$CHALLENGE_FILE" 2>/dev/null || true; }

is_challenge() { [ -f "$CHALLENGE_FILE" ]; }
