#!/usr/bin/env bash
# On the outer Ubuntu VM: create a new Proxmox VM. This never installs PVE on Ubuntu.
set -euo pipefail
root="$(realpath "${1:?Usage: sudo bash create-nested-proxmox.sh MEDIA SITE.json}")"
config="$(realpath "${2:?Site JSON required}")"
test "$(id -u)" = 0
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 26.04 || { echo 'Outer VM must run Ubuntu 26.04' >&2; exit 1; }
python3 "$root/scripts/verify-media.py" "$root"
eval "$(python3 "$root/scripts/validate-site.py" "$config" --shell)"
grep -Eq '(vmx|svm)' /proc/cpuinfo || { echo 'The outer hypervisor has not exposed virtualization CPU features.' >&2; exit 1; }
bash "$root/scripts/offline-apt.sh" "$root" qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst bridge-utils
if grep -q GenuineIntel /proc/cpuinfo; then
  printf 'options kvm_intel nested=1\n' > /etc/modprobe.d/academy-nested.conf
  modprobe kvm_intel
  test "$(cat /sys/module/kvm_intel/parameters/nested)" = Y || { echo 'Enable Intel nested KVM and reboot the outer Ubuntu VM.' >&2; exit 1; }
else
  printf 'options kvm_amd nested=1\n' > /etc/modprobe.d/academy-nested.conf
  modprobe kvm_amd
  test "$(cat /sys/module/kvm_amd/parameters/nested)" = 1 || { echo 'Enable AMD nested KVM and reboot the outer Ubuntu VM.' >&2; exit 1; }
fi
test -c /dev/kvm || { echo 'KVM is unavailable in the outer Ubuntu VM.' >&2; exit 1; }
systemctl enable --now libvirtd
ip link show "$SITE_OUTER_LIBVIRT_BRIDGE" | grep -q '<.*UP' || { echo "Create and bring up the LAN bridge $SITE_OUTER_LIBVIRT_BRIDGE first. See INSTALL.md." >&2; exit 1; }
test -d "/sys/class/net/$SITE_OUTER_LIBVIRT_BRIDGE/bridge" || { echo 'Configured interface is not a Linux bridge' >&2; exit 1; }
if virsh --connect qemu:///system dominfo "$SITE_NESTED_VM_NAME" >/dev/null 2>&1; then
  echo 'The named nested VM already exists. Reconnect to its console; no existing disk was changed.' >&2; exit 1
fi
install -d -m 755 /var/lib/libvirt/images/academy
disk="/var/lib/libvirt/images/academy/$SITE_NESTED_VM_NAME.qcow2"
test ! -e "$disk" || { echo 'Target disk already exists; refusing to replace it.' >&2; exit 1; }
qemu-img create -f qcow2 "$disk" "${SITE_NESTED_DISK_GB}G"
# Copy the installer into libvirt-readable storage; removable mount permissions vary.
install -m 644 "$root/assets/proxmox/proxmox.iso" /var/lib/libvirt/images/academy/proxmox.iso
virt-install --connect qemu:///system --name "$SITE_NESTED_VM_NAME" \
  --metadata description=USCCAcademyNestedHypervisor \
  --memory "$SITE_NESTED_MEMORY_MB" --vcpus "$SITE_NESTED_CORES" --cpu host-passthrough \
  --osinfo detect=on,require=off --virt-type kvm \
  --disk "path=$disk,format=qcow2,bus=virtio" \
  --cdrom /var/lib/libvirt/images/academy/proxmox.iso \
  --network "bridge=$SITE_OUTER_LIBVIRT_BRIDGE,model=virtio" \
  --graphics vnc,listen=127.0.0.1 --noautoconsole
virsh --connect qemu:///system autostart "$SITE_NESTED_VM_NAME"
echo 'Proxmox VM created. Open its VNC console locally or through an SSH tunnel and complete the stock Proxmox installer.'
echo 'Use the configured Proxmox hostname/IP. The installation target is the new blank virtual disk.'
