#!/usr/bin/env bash
# netlab :: lib/topology.sh -- build / tear down the network-namespace lab
#
# Everything the drills touch lives inside network namespaces. Your real NIC,
# real routing table and real firewall are NOT modified by "netlab lab up"
# except for two clearly-marked, easily-reversible host items:
#   1. a veth pair (nl-up-h) giving the host a door into the lab
#   2. optional IP forwarding + a MASQUERADE rule so the lab can reach the
#      internet. Both are removed by "netlab lab down".

# ------------------------------------------------------------- host uplink --
host_default_iface() {
  ip -4 route show default 2>/dev/null | awk '/default/ {print $5; exit}'
}

# ---------------------------------------------------------------- content ---
seed_web_content() {
  mkdir -p "$NETLAB_WWW"
  {
    printf '%s\n' '<!doctype html><meta charset="utf-8"><title>netlab server</title>'
    printf '%s\n' '<h1>netlab web server</h1>'
    printf '%s\n' '<p>You reached 10.10.2.10. Routing and firewalling are working.</p>'
  } > "$NETLAB_WWW/index.html"
  printf 'netlab-ok\n' > "$NETLAB_WWW/health"
  # 6 MB file: used by the MTU / PMTU black-hole drill
  if [ ! -s "$NETLAB_WWW/big.bin" ]; then
    dd if=/dev/urandom of="$NETLAB_WWW/big.bin" bs=1M count=6 status=none 2>/dev/null \
      || head -c 6291456 /dev/urandom > "$NETLAB_WWW/big.bin"
  fi
}

# --------------------------------------------------------------- ns files ---
seed_ns_etc() {
  # "ip netns exec" bind-mounts /etc/netns/<ns>/* over /etc/*, so each namespace
  # gets its own resolv.conf and hosts file.
  local ns
  for ns in "${NETLAB_NAMESPACES[@]}"; do
    mkdir -p "/etc/netns/$ns"
    {
      printf '%s\n' 'nameserver 1.1.1.1'
      printf '%s\n' 'nameserver 8.8.8.8'
      printf '%s\n' 'options timeout:2 attempts:1'
    } > "/etc/netns/$ns/resolv.conf"
    {
      printf '%s\n' '127.0.0.1   localhost'
      printf '%s\n' '10.10.2.10  web.lab.local web'
      printf '%s\n' '10.10.1.1   gw.lab.local gw'
    } > "/etc/netns/$ns/hosts"
  done
}

# ---------------------------------------------------------------- veth up ---
# _mkveth <tmpA> <nsA> <finalA> <tmpB> <nsB> <finalB>
# nsA/nsB may be the literal word "host" to keep the device in the root ns.
_mkveth() {
  local ta="$1" na="$2" aa="$3" tb="$4" nb="$5" ab="$6"
  ip link del "$ta" 2>/dev/null || true
  ip link add "$ta" type veth peer name "$tb"
  if [ "$na" = "host" ]; then
    ip link set "$ta" name "$aa"
  else
    ip link set "$ta" netns "$na"
    ip netns exec "$na" ip link set "$ta" name "$aa"
  fi
  if [ "$nb" = "host" ]; then
    ip link set "$tb" name "$ab"
  else
    ip link set "$tb" netns "$nb"
    ip netns exec "$nb" ip link set "$tb" name "$ab"
  fi
}

topo_up() {
  need_root "lab up"
  ensure_dirs
  seed_web_content

  if topo_is_up; then
    info "Topology already up. Use 'sudo netlab lab rebuild' for a clean slate."
    return 0
  fi

  info "Creating network namespaces..."
  local ns
  for ns in "${NETLAB_NAMESPACES[@]}"; do
    ip netns add "$ns" 2>/dev/null || true
    ip netns exec "$ns" ip link set lo up
  done

  seed_ns_etc

  info "Wiring veth pairs..."
  _mkveth nlv0 "$NS_CLIENT" eth0        nlv1 "$NS_ROUTER" lan0
  _mkveth nlv2 "$NS_SERVER" eth0        nlv3 "$NS_ROUTER" dmz0
  _mkveth nlv4 host         "$HOST_VETH" nlv5 "$NS_ROUTER" up0

  info "Assigning addresses..."
  nsx client ip addr add "$CLIENT_IP/24" dev eth0
  nsx client ip link set eth0 up
  nsx client ip route replace default via "$ROUTER_LAN_IP"

  nsx server ip addr add "$SERVER_IP/24" dev eth0
  nsx server ip link set eth0 up
  nsx server ip route replace default via "$ROUTER_DMZ_IP"

  nsx router ip addr add "$ROUTER_LAN_IP/24" dev lan0
  nsx router ip addr add "$ROUTER_DMZ_IP/24" dev dmz0
  nsx router ip addr add "$ROUTER_UP_IP/24" dev up0
  nsx router ip link set lan0 up
  nsx router ip link set dmz0 up
  nsx router ip link set up0 up
  nsx router ip route replace default via "$HOST_UP_IP"
  nsx router sysctl -qw net.ipv4.ip_forward=1

  # host side of the uplink
  ip addr add "$HOST_UP_IP/24" dev "$HOST_VETH" 2>/dev/null || true
  ip link set "$HOST_VETH" up
  ip route replace "$LAN_NET" via "$ROUTER_UP_IP" dev "$HOST_VETH"
  ip route replace "$DMZ_NET" via "$ROUTER_UP_IP" dev "$HOST_VETH"

  topo_uplink_on
  topo_services_start

  ok "Topology is up."
  topo_diagram
}

# ------------------------------------------------------------ host NAT/fwd --
topo_uplink_on() {
  local wan
  wan="$(host_default_iface)"
  printf '%s\n' "${wan:-none}" > "$NETLAB_RUN_DIR/wan_iface"
  sysctl -qw net.ipv4.ip_forward=1
  if [ -n "$wan" ]; then
    iptables -t nat -C POSTROUTING -s "$LAB_SUPERNET" -o "$wan" -j MASQUERADE 2>/dev/null \
      || iptables -t nat -A POSTROUTING -s "$LAB_SUPERNET" -o "$wan" -j MASQUERADE
    iptables -C FORWARD -s "$LAB_SUPERNET" -j ACCEPT 2>/dev/null \
      || iptables -I FORWARD 1 -s "$LAB_SUPERNET" -j ACCEPT
    iptables -C FORWARD -d "$LAB_SUPERNET" -j ACCEPT 2>/dev/null \
      || iptables -I FORWARD 1 -d "$LAB_SUPERNET" -j ACCEPT
    info "Host NAT enabled via $wan (lab can reach the internet)."
  else
    warn "No default route on the host; the lab will have no internet."
    warn "That is fine -- every drill except net-07 works fully offline."
  fi
}

topo_uplink_off() {
  local wan
  wan="$(cat "$NETLAB_RUN_DIR/wan_iface" 2>/dev/null || true)"
  [ "$wan" = "none" ] && wan=""
  [ -z "$wan" ] && wan="$(host_default_iface)"
  if [ -n "$wan" ]; then
    while iptables -t nat -C POSTROUTING -s "$LAB_SUPERNET" -o "$wan" -j MASQUERADE 2>/dev/null; do
      iptables -t nat -D POSTROUTING -s "$LAB_SUPERNET" -o "$wan" -j MASQUERADE
    done
  fi
  while iptables -C FORWARD -s "$LAB_SUPERNET" -j ACCEPT 2>/dev/null; do
    iptables -D FORWARD -s "$LAB_SUPERNET" -j ACCEPT
  done
  while iptables -C FORWARD -d "$LAB_SUPERNET" -j ACCEPT 2>/dev/null; do
    iptables -D FORWARD -d "$LAB_SUPERNET" -j ACCEPT
  done
}

# --------------------------------------------------------------- services --
topo_services_start() {
  topo_services_stop
  info "Starting lab web services (ports $HTTP_PORT and $ALT_PORT on the server)..."
  nsx server bash -c "cd '$NETLAB_WWW' && nohup python3 -m http.server $HTTP_PORT --bind 0.0.0.0 >>'$NETLAB_LOG' 2>&1 & echo \$! > '$NETLAB_RUN_DIR/http8080.pid'"
  nsx server bash -c "cd '$NETLAB_WWW' && nohup python3 -m http.server $ALT_PORT --bind 0.0.0.0 >>'$NETLAB_LOG' 2>&1 & echo \$! > '$NETLAB_RUN_DIR/http9090.pid'"
  sleep 1
}

topo_services_stop() {
  local p f
  for f in "$NETLAB_RUN_DIR"/http*.pid; do
    [ -e "$f" ] || continue
    p="$(cat "$f" 2>/dev/null || true)"
    [ -n "$p" ] && kill "$p" 2>/dev/null || true
    rm -f "$f"
  done
}

topo_services_ok() {
  t_http server "http://127.0.0.1:$HTTP_PORT/health" 3
}

# --------------------------------------------------------------- tear down --
topo_down() {
  need_root "lab down"
  info "Stopping services..."
  topo_services_stop
  info "Removing namespaces..."
  local ns
  for ns in "${NETLAB_NAMESPACES[@]}"; do
    ip netns del "$ns" 2>/dev/null || true
    rm -rf "/etc/netns/$ns"
  done
  info "Removing host uplink and NAT..."
  topo_uplink_off
  ip route del "$LAN_NET" 2>/dev/null || true
  ip route del "$DMZ_NET" 2>/dev/null || true
  ip link del "$HOST_VETH" 2>/dev/null || true
  ip link del nlv0 2>/dev/null || true
  ip link del nlv2 2>/dev/null || true
  ip link del nlv4 2>/dev/null || true
  active_clear
  ok "Topology removed. Your host networking is untouched."
}

topo_rebuild() {
  topo_down >/dev/null 2>&1 || true
  topo_up
}

# ------------------------------------------------------------ known-good ----
# Re-apply the correct configuration everywhere. Used by "netlab reset".
topo_repair() {
  require_topo
  nsx client ip link set eth0 up 2>/dev/null || true
  nsx client ip addr flush dev eth0 2>/dev/null || true
  nsx client ip addr add "$CLIENT_IP/24" dev eth0 2>/dev/null || true
  nsx client ip link set eth0 mtu 1500 2>/dev/null || true
  nsx client ip route replace default via "$ROUTER_LAN_IP" 2>/dev/null || true
  nsx client ip neigh flush all 2>/dev/null || true

  nsx server ip link set eth0 up 2>/dev/null || true
  nsx server ip addr flush dev eth0 2>/dev/null || true
  nsx server ip addr add "$SERVER_IP/24" dev eth0 2>/dev/null || true
  nsx server ip link set eth0 mtu 1500 2>/dev/null || true
  nsx server ip route replace default via "$ROUTER_DMZ_IP" 2>/dev/null || true

  nsx router ip link set lan0 up 2>/dev/null || true
  nsx router ip link set dmz0 up 2>/dev/null || true
  nsx router ip link set up0 up 2>/dev/null || true
  nsx router ip link set lan0 mtu 1500 2>/dev/null || true
  nsx router ip link set dmz0 mtu 1500 2>/dev/null || true
  nsx router ip addr flush dev lan0 2>/dev/null || true
  nsx router ip addr flush dev dmz0 2>/dev/null || true
  nsx router ip addr flush dev up0 2>/dev/null || true
  nsx router ip addr add "$ROUTER_LAN_IP/24" dev lan0 2>/dev/null || true
  nsx router ip addr add "$ROUTER_DMZ_IP/24" dev dmz0 2>/dev/null || true
  nsx router ip addr add "$ROUTER_UP_IP/24" dev up0 2>/dev/null || true
  nsx router ip route replace default via "$HOST_UP_IP" 2>/dev/null || true
  nsx router sysctl -qw net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

  fw_flush_ns client
  fw_flush_ns router
  fw_flush_ns server

  seed_ns_etc
  topo_services_start >/dev/null 2>&1
}

# Flush every table in one namespace back to "allow everything".
fw_flush_ns() {
  local ns="$1" t
  for t in filter nat mangle; do
    nsx "$ns" iptables -t "$t" -F 2>/dev/null || true
    nsx "$ns" iptables -t "$t" -X 2>/dev/null || true
  done
  local c
  for c in INPUT FORWARD OUTPUT; do
    nsx "$ns" iptables -P "$c" ACCEPT 2>/dev/null || true
  done
}

# ----------------------------------------------------------------- diagram --
topo_diagram() {
  printf '\n%sLab topology%s  %s(all inside network namespaces -- safe to break)%s\n\n' \
    "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
  printf '%s\n' '     nl-client                nl-router                  nl-server'
  printf '%s\n' '   +------------+        +----------------+          +------------+'
  printf '%s\n' '   |    eth0    |--------| lan0      dmz0 |----------|    eth0    |'
  printf '%s\n' '   | 10.10.1.10 |        | 10.10.1.1      |          | 10.10.2.10 |'
  printf '%s\n' '   +------------+        |      10.10.2.1 |          |   :8080    |'
  printf '%s\n' '                         |      up0       |          |   :9090    |'
  printf '%s\n' '                         |   10.10.0.2    |          +------------+'
  printf '%s\n' '                         +-------|--------+'
  printf '%s\n' '                                 |'
  printf '%s\n' '                          nl-up-h 10.10.0.1'
  printf '%s\n' '                             [ your VM ]'
  printf '\n'
  printf '   Enter a namespace:  %ssudo netlab sh client%s\n' "$C_GREEN" "$C_RESET"
  printf '   One-off command:    %ssudo netlab exec client ip -br addr%s\n\n' "$C_GREEN" "$C_RESET"
}
