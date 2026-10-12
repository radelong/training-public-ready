#!/usr/bin/env bash
# First boot inside a disposable Ubuntu template VM.
set -euo pipefail
root="$(realpath "${1:?Media path}")"; kind="${2:?netlab or linux}"
case "$kind" in netlab|linux) :;; *) echo 'Unsupported template kind' >&2; exit 1;; esac
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 26.04
bash "$root/scripts/offline-apt.sh" "$root" qemu-guest-agent openssh-server sudo \
  iproute2 iptables iputils-ping iputils-arping traceroute tcpdump curl wget dnsutils \
  netcat-openbsd socat conntrack ethtool python3 jq less bash-completion ipcalc mtr-tiny nftables
systemctl start qemu-guest-agent
systemctl enable --now ssh
bash "$root/vendor/netlab/install.sh" --no-apt
# Ubuntu 26.04 emits OSC 3008 shell metadata that the embedded SSH terminal
# displays as long, unrelated strings. Keep the learner's interactive shell clean.
cat >> /home/learner/.bashrc <<'EOF'

# Keep the browser lab terminal free of systemd OSC 3008 prompt metadata.
unset PROMPT_COMMAND
PS0=''
EOF
chown learner:learner /home/learner/.bashrc
touch /home/learner/.hushlogin
chown learner:learner /home/learner/.hushlogin
install -m 755 "$root/scripts/academy-lab" /usr/local/sbin/academy-lab
install -m 755 "$root/scripts/academy-linux" /usr/local/sbin/academy-linux
printf '%s\n' "$kind" > /etc/academy-lab-kind
if [ "$kind" = netlab ]; then
  install -d -m 755 /opt/academy/k3s
  cp -a "$root/assets/k3s/." /opt/academy/k3s/
  install -m 755 "$root/scripts/academy-k3s-firstboot.sh" /usr/local/sbin/academy-k3s-firstboot
  install -m 644 "$root/deploy/academy-k3s-firstboot.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable academy-k3s-firstboot.service
fi
if [ "$kind" = linux ]; then
  bash "$root/scripts/offline-apt.sh" "$root" docker.io
  systemctl enable --now docker
  docker load -i "$root/assets/images/linux.tar"
  # Docker access is equivalent to root, appropriate only inside this disposable VM.
  usermod -aG docker learner
fi
printf 'learner ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/academy-learner
chmod 440 /etc/sudoers.d/academy-learner
printf 'PasswordAuthentication no\nPermitRootLogin no\nHostKey /etc/ssh/ssh_host_rsa_key\n' > /etc/ssh/sshd_config.d/academy.conf
systemctl restart ssh
touch /var/lib/academy-template-ready
