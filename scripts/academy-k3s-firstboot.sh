#!/usr/bin/env bash
# Run once in each newly cloned Netlab VM. All inputs are already on its disk.
set -euo pipefail
assets=/opt/academy/k3s
ready=/var/lib/academy-k3s-ready
test -f /var/lib/academy-template-ready
test "$(cat /etc/academy-lab-kind)" = netlab
if test -f "$ready"; then exit 0; fi

test -f "$assets/k3s"
test -f "$assets/k3s-airgap-images-amd64.tar.gz"
test -f "$assets/nginx-1.27-alpine-docker.tar"
test -f "$assets/busybox-1.36-docker.tar"
(cd "$assets" && sha256sum -c sha256sum-amd64.txt --ignore-missing)

node_ip="$(ip -4 -o addr show dev eth0 scope global | awk 'NR==1 {split($4,a,"/"); print a[1]}')"
test -n "$node_ip"
install -m 0755 "$assets/k3s" /usr/local/bin/k3s
install -d -m 0755 /var/lib/rancher/k3s/agent/images
install -m 0644 "$assets/k3s-airgap-images-amd64.tar.gz" \
  /var/lib/rancher/k3s/agent/images/k3s-airgap-images-amd64.tar.gz

INSTALL_K3S_SKIP_DOWNLOAD=true \
INSTALL_K3S_SKIP_START=true \
INSTALL_K3S_EXEC="server --disable traefik --disable metrics-server --write-kubeconfig-mode 644 --flannel-iface eth0 --node-ip $node_ip" \
  sh "$assets/install.sh"
systemctl start --no-block k3s

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
for attempt in $(seq 1 180); do
  if /usr/local/bin/k3s kubectl get nodes --no-headers 2>/dev/null | grep -q ' Ready '; then break; fi
  sleep 2
done
/usr/local/bin/k3s kubectl get nodes --no-headers | grep -q ' Ready '

# K3s imports its own airgap archive in the background. On nested storage that
# can take much longer than node registration; wait before importing the drill
# images so containerd is not asked to unpack both archives at once.
for attempt in $(seq 1 240); do
  if /usr/local/bin/k3s kubectl -n kube-system get deployment/coredns >/dev/null 2>&1; then break; fi
  sleep 10
done
/usr/local/bin/k3s kubectl -n kube-system rollout status deployment/coredns --timeout=2400s

# The practice images are separate from the K3s system-image airgap archive.
for image in "$assets"/*-docker.tar; do
  /usr/local/bin/k3s ctr -n k8s.io images import "$image"
done
images="$(/usr/local/bin/k3s ctr -n k8s.io images list -q)"
grep -q 'nginx:1.27-alpine' <<< "$images"
grep -q 'busybox:1.36' <<< "$images"
/opt/netlab/bin/netlab k8s up
/usr/local/bin/k3s kubectl -n netlab wait --for=condition=Ready pod/toolbox --timeout=180s
touch "$ready"
