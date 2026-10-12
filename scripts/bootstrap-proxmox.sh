#!/usr/bin/env bash
# Run as root on a dedicated, newly installed Proxmox 9+ node.
set -euo pipefail
root="$(realpath "${1:?Usage: bash bootstrap-proxmox.sh MEDIA SITE.json PROVISION.iso}")"
config="$(realpath "${2:?Site JSON required}")"
iso="$(realpath "${3:?academy-provision.iso required}")"
test -f "$iso.sha256" || { echo 'Provision ISO checksum sidecar is required.' >&2; exit 1; }
read -r iso_checksum _ < "$iso.sha256"
[[ "$iso_checksum" =~ ^[a-fA-F0-9]{64}$ ]]
printf '%s  %s\n' "$iso_checksum" "$iso" | sha256sum --check --status
test "$(id -u)" = 0
command -v qm >/dev/null
command -v python3 >/dev/null
pveversion | grep -Eq 'pve-manager/(9|[1-9][0-9])\.' || { echo 'This installer targets Proxmox VE 9 or newer.' >&2; exit 1; }
python3 "$root/scripts/verify-media.py" "$root"
eval "$(python3 "$root/scripts/validate-site.py" "$config" --shell)"
test "$(hostname -s)" = "$SITE_PVE_NODE" || { echo 'Site pve_node does not match this node hostname.' >&2; exit 1; }
test -c /dev/kvm && grep -Eq '(vmx|svm)' /proc/cpuinfo || { echo 'Nested KVM features are not exposed to Proxmox.' >&2; exit 1; }
# Refuse to change a populated node or restart a partially completed bootstrap.
vm_listing="$(qm list)"
if grep -Eq '^[[:space:]]*[0-9]+[[:space:]]' <<< "$vm_listing"; then
  echo 'Use a dedicated empty Proxmox node. Existing VMs were not changed.' >&2
  exit 1
fi
test ! -e /root/academy-bootstrap || { echo 'Bootstrap state already exists. Follow the recovery instructions.' >&2; exit 1; }
ip link show "$SITE_PVE_MANAGEMENT_BRIDGE" >/dev/null
pvesm status --storage "$SITE_PVE_STORAGE" | grep -q active
install -d -m 700 /root/academy-bootstrap
work=/root/academy-bootstrap
cp "$config" "$work/site.json"
ssh-keygen -q -t rsa -b 3072 -N '' -f "$work/bootstrap-key"
if ! ip link show "$SITE_PVE_LAB_BRIDGE" >/dev/null 2>&1; then
  mkdir -p /etc/network/interfaces.d
  printf 'auto %s\niface %s inet manual\n    bridge-ports none\n    bridge-stp off\n    bridge-fd 0\n' \
    "$SITE_PVE_LAB_BRIDGE" "$SITE_PVE_LAB_BRIDGE" > /etc/network/interfaces.d/academy-lab
  grep -Eq '^source.*interfaces.d' /etc/network/interfaces || printf '\nsource /etc/network/interfaces.d/*\n' >> /etc/network/interfaces
  ifup "$SITE_PVE_LAB_BRIDGE"
fi
# Guacd needs an isolated learner bridge; it is not attached to physical LAN ports.
test -z "$(bridge link show master "$SITE_PVE_LAB_BRIDGE")" || { echo 'Lab bridge has physical ports; use an isolated bridge.' >&2; exit 1; }
if [ "$SITE_SERVICES_NETWORK_MODE" = private_nat ]; then
  # Keep the services guest off the LAN. Only HTTPS on the PVE LAN address is
  # forwarded to it; outbound guest traffic uses the node address for DNS.
  test ! -e "/etc/network/interfaces.d/academy-services" || { echo 'Private services bridge configuration already exists.' >&2; exit 1; }
  test ! -e "/sys/class/net/$SITE_PVE_SERVICES_BRIDGE" || { echo 'Private services bridge already exists.' >&2; exit 1; }
  cat > /etc/network/interfaces.d/academy-services <<EOF
auto $SITE_PVE_SERVICES_BRIDGE
iface $SITE_PVE_SERVICES_BRIDGE inet static
    address $SITE_MANAGEMENT_GATEWAY/${SITE_SERVICES_MANAGEMENT_IP#*/}
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up iptables -t nat -C PREROUTING -i $SITE_PVE_MANAGEMENT_BRIDGE -s $SITE_ACADEMY_LAN_CIDR -d $SITE_ACADEMY_PUBLIC_IP -p tcp --dport 443 -j DNAT --to-destination ${SITE_SERVICES_MANAGEMENT_IP%/*}:443 || iptables -t nat -A PREROUTING -i $SITE_PVE_MANAGEMENT_BRIDGE -s $SITE_ACADEMY_LAN_CIDR -d $SITE_ACADEMY_PUBLIC_IP -p tcp --dport 443 -j DNAT --to-destination ${SITE_SERVICES_MANAGEMENT_IP%/*}:443
    post-up iptables -t nat -C POSTROUTING -s ${SITE_SERVICES_MANAGEMENT_IP%/*}/32 -o $SITE_PVE_MANAGEMENT_BRIDGE -j MASQUERADE || iptables -t nat -A POSTROUTING -s ${SITE_SERVICES_MANAGEMENT_IP%/*}/32 -o $SITE_PVE_MANAGEMENT_BRIDGE -j MASQUERADE
    post-down iptables -t nat -D PREROUTING -i $SITE_PVE_MANAGEMENT_BRIDGE -s $SITE_ACADEMY_LAN_CIDR -d $SITE_ACADEMY_PUBLIC_IP -p tcp --dport 443 -j DNAT --to-destination ${SITE_SERVICES_MANAGEMENT_IP%/*}:443 || true
    post-down iptables -t nat -D POSTROUTING -s ${SITE_SERVICES_MANAGEMENT_IP%/*}/32 -o $SITE_PVE_MANAGEMENT_BRIDGE -j MASQUERADE || true
EOF
  printf 'net.ipv4.ip_forward=1\n' > /etc/sysctl.d/90-academy-private.conf
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
  ifup "$SITE_PVE_SERVICES_BRIDGE"
  ip -4 addr show dev "$SITE_PVE_SERVICES_BRIDGE" | grep -Fq "$SITE_MANAGEMENT_GATEWAY/${SITE_SERVICES_MANAGEMENT_IP#*/}"
fi
pveum user add academy@pve --comment 'Local academy provisioning service'
pveum role add AcademyVM --privs 'VM.Audit VM.Allocate VM.Config.CPU VM.Config.Memory VM.Config.Network VM.Config.Disk VM.Config.Cloudinit VM.Config.Options VM.PowerMgmt VM.GuestAgent.Unrestricted VM.GuestAgent.Audit'
pveum role add AcademyTemplate --privs 'VM.Audit VM.Clone'
pveum role add AcademyStorage --privs 'Datastore.Audit Datastore.AllocateSpace'
pveum role add AcademyBridge --privs 'SDN.Use'
pveum pool add academy-learners --comment 'Disposable training academy learner VMs'
pveum acl modify /pool/academy-learners --users academy@pve --roles AcademyVM
for vmid in "$SITE_NET_TEMPLATE_ID" "$SITE_LINUX_TEMPLATE_ID"; do
  pveum acl modify "/vms/$vmid" --users academy@pve --roles AcademyTemplate
done
pveum acl modify "/storage/$SITE_PVE_STORAGE" --users academy@pve --roles AcademyStorage
pveum acl modify "/sdn/zones/localnetwork/$SITE_PVE_LAB_BRIDGE" --users academy@pve --roles AcademyBridge
pveum user token add academy@pve portal --privsep 0 --output-format json > "$work/token.json"
python3 - "$work/site.json" "$work/token.json" <<'PY'
import base64,json,sys
from pathlib import Path
file=Path(sys.argv[1]); config=json.loads(file.read_text()); token=json.loads(Path(sys.argv[2]).read_text())
config['proxmox_connection']={'token_id':'academy@pve!portal','token_secret':token['value'],
  'ca_pem_base64':base64.b64encode(Path('/etc/pve/pve-root-ca.pem').read_bytes()).decode()}
file.write_text(json.dumps(config,indent=2))
PY
chmod 600 "$work/site.json" "$work/token.json"
# Enable firewall filtering on this dedicated training node.
pvesh set /cluster/firewall/options --enable 1
systemctl enable --now pve-firewall
# Host firewall defaults allow management from the LAN but block the private
# services subnet. Permit the one services VM to reach the local API.
bash "$root/scripts/allow-academy-api.sh" "$work/site.json"
# Standard directory storage is required for ISO files and snippets.
iso_path="$(pvesm path "$SITE_PVE_ISO_STORAGE:iso/academy-provision.iso")"
install -d "$(dirname "$iso_path")"
install -m 644 "$iso" "$iso_path"
storage_base="$(dirname "$(dirname "$(dirname "$iso_path")")")"
snippets="$storage_base/snippets"
install -d "$snippets"
current_content="$(pvesh get "/storage/$SITE_PVE_ISO_STORAGE" --output-format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["content"])')"
if [[ ",$current_content," != *,snippets,* ]]; then pvesm set "$SITE_PVE_ISO_STORAGE" --content "$current_content,snippets"; fi
create_vm() {
  local vmid="$1" kind="$2" memory="$3" cores="$4" size="$5"
  local name="academy-$kind"
  qm create "$vmid" --name "$name" --memory "$memory" --cores "$cores" --cpu host \
    --scsihw virtio-scsi-pci --agent enabled=1 --serial0 socket --vga serial0
  qm importdisk "$vmid" "$root/assets/ubuntu/ubuntu-26.04-server-cloudimg-amd64.img" "$SITE_PVE_STORAGE"
  local imported
  imported="$(qm config "$vmid" | sed -n 's/^unused0: //p')"
  test -n "$imported"
  qm set "$vmid" --scsi0 "$imported" --ide2 "$SITE_PVE_STORAGE:cloudinit" \
    --ide0 "$SITE_PVE_ISO_STORAGE:iso/academy-provision.iso,media=cdrom" --boot order=scsi0
  qm resize "$vmid" scsi0 "${size}G"
  python3 "$root/scripts/guest-cloud-init.py" "$kind" "$work/site.json" "$work/bootstrap-key.pub" "$snippets/academy-$vmid.yaml"
  qm set "$vmid" --cicustom "user=$SITE_PVE_ISO_STORAGE:snippets/academy-$vmid.yaml" --ciuser learner \
    --sshkeys "$work/bootstrap-key.pub"
  if [ "$kind" = services ]; then
    services_bridge="$SITE_PVE_MANAGEMENT_BRIDGE"
    [ "$SITE_SERVICES_NETWORK_MODE" != private_nat ] || services_bridge="$SITE_PVE_SERVICES_BRIDGE"
    qm set "$vmid" --net0 "virtio,bridge=$services_bridge" --net1 "virtio,bridge=$SITE_PVE_LAB_BRIDGE" \
      --ipconfig0 "ip=$SITE_SERVICES_MANAGEMENT_IP,gw=$SITE_MANAGEMENT_GATEWAY" \
      --ipconfig1 "ip=$SITE_SERVICES_LAB_IP" --nameserver "$SITE_MANAGEMENT_DNS" --onboot 1
  else
    local temporary_ip=20; [ "$kind" = linux ] && temporary_ip=21
    qm set "$vmid" --net0 "virtio,bridge=$SITE_PVE_LAB_BRIDGE" \
      --ipconfig0 "ip=$SITE_LAB_PREFIX.$temporary_ip/24" --onboot 0
  fi
  qm start "$vmid"
}
wait_bootstrap() {
  local vmid="$1" result pid
  for attempt in $(seq 1 180); do
    result="$(qm guest exec "$vmid" -- /usr/bin/test -f /var/lib/academy-bootstrap-complete 2>/dev/null || true)"
    if printf '%s' "$result" | python3 -c 'import json,sys; v=json.load(sys.stdin);sys.exit(0 if v.get("exitcode")==0 and v.get("exited") else 1)' 2>/dev/null; then return; fi
    sleep 5
  done
  echo "VM $vmid bootstrap did not complete. Inspect its console and /var/log/cloud-init-output.log." >&2; exit 1
}
for specification in "$SITE_NET_TEMPLATE_ID:netlab" "$SITE_LINUX_TEMPLATE_ID:linux"; do
  vmid="${specification%%:*}"; kind="${specification#*:}"
  memory=2048; [ "$kind" != netlab ] || memory=4096
  create_vm "$vmid" "$kind" "$memory" 2 "$SITE_LAB_DISK_GB"
  wait_bootstrap "$vmid"
  qm guest exec "$vmid" -- /bin/bash -c 'cloud-init status --wait >/dev/null; cloud-init clean --logs --machine-id; rm -f /etc/ssh/ssh_host_*; rm -f /home/learner/.ssh/authorized_keys'
  qm shutdown "$vmid" --timeout 120
  qm set "$vmid" --delete cicustom,ide0 --sshkeys /dev/null
  qm template "$vmid"
done
create_vm "$SITE_SERVICES_VMID" services "$SITE_SERVICES_MEMORY_MB" "$SITE_SERVICES_CORES" "$SITE_SERVICES_DISK_GB"
wait_bootstrap "$SITE_SERVICES_VMID"
# Templates are activated in the portal after the acceptance test; they are not enabled silently.
echo "Services VM and lab templates prepared. Open https://$SITE_HOSTNAME and complete the acceptance checklist."
echo 'Retrieve the initial administrator password through the services VM console. Bootstrap keys/configuration are in /root/academy-bootstrap.'
