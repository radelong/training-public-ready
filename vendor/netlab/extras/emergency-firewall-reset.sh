#!/usr/bin/env bash
# EMERGENCY: flush every firewall rule and allow all traffic.
# Run this from the CONSOLE if you have locked yourself out over SSH.
#
#   sudo /opt/netlab/extras/emergency-firewall-reset.sh
#
# Policies are set to ACCEPT FIRST. Flushing rules while the policy is still
# DROP disconnects you instantly -- that ordering is the whole point.
set -u

for t in filter nat mangle raw; do
  iptables  -t "$t" -P INPUT   ACCEPT 2>/dev/null || true
  iptables  -t "$t" -P FORWARD ACCEPT 2>/dev/null || true
  iptables  -t "$t" -P OUTPUT  ACCEPT 2>/dev/null || true
done

for cmd in iptables ip6tables; do
  command -v "$cmd" >/dev/null 2>&1 || continue
  "$cmd" -P INPUT   ACCEPT 2>/dev/null || true
  "$cmd" -P FORWARD ACCEPT 2>/dev/null || true
  "$cmd" -P OUTPUT  ACCEPT 2>/dev/null || true
  for t in filter nat mangle raw; do
    "$cmd" -t "$t" -F 2>/dev/null || true
    "$cmd" -t "$t" -X 2>/dev/null || true
  done
done

echo "All firewall rules flushed and policies set to ACCEPT."
echo "The machine is now UNFIREWALLED. Restore a known-good ruleset:"
echo "  sudo netlab snapshot list"
echo "  sudo netlab snapshot restore <name>"
echo "  sudo iptables-restore < /etc/iptables/rules.v4"
