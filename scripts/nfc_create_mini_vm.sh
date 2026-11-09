#!/usr/bin/env bash
# Mini AI isolated libvirt guest on NFC. --check is read-only and the default.
# Never edits existing guest definitions, VM disks, or host networking.
set -Eeuo pipefail
mode=--check
if (( $# > 0 )); then mode="$1"; fi
[[ "$mode" == --check || "$mode" == --create ]] || { echo "Usage: bash scripts/nfc_create_mini_vm.sh [--check|--create]" >&2; exit 2; }
vm=mini-ai-inference
pool=images
key=/root/mini-ai-operator.pub
work=/root/mini-ai-provision
image=ubuntu-24.04-server-cloudimg-amd64.img
image_base=https://cloud-images.ubuntu.com/releases/noble/release
for cmd in virsh virt-install qemu-img python3 curl sha256sum; do
  command -v "$cmd" >/dev/null || { echo "MISSING TOOL: $cmd" >&2; exit 1; }
done
[[ "$(virsh uri)" == qemu:///system ]] || { echo "BLOCKED: unexpected libvirt URI" >&2; exit 1; }
virsh pool-info "$pool" | grep -E '^State:[[:space:]]+running$' >/dev/null || { echo "BLOCKED: images pool inactive"; exit 1; }
virsh net-info default | grep -E '^Active:[[:space:]]+yes$' >/dev/null || { echo "BLOCKED: default NAT inactive"; exit 1; }
pool_dir="$(virsh pool-dumpxml "$pool" | python3 -c 'import sys,xml.etree.ElementTree as ET; print(ET.parse(sys.stdin).findtext("./target/path") or "")')"
[[ -n "$pool_dir" && -d "$pool_dir" ]] || { echo "BLOCKED: pool directory missing"; exit 1; }
if virsh dominfo "$vm" >/dev/null 2>&1; then echo "BLOCKED: VM name already exists"; exit 2; fi
disk="$pool_dir/$vm.qcow2"
[[ ! -e "$disk" && ! -e "$disk.part" ]] || { echo "BLOCKED: guest disk already exists"; exit 2; }
read -r mem_gib free_gib < <(python3 - "$pool_dir" <<'PY'
import shutil, sys
with open("/proc/meminfo") as f:
    mem = next(int(s.split()[1]) / 1048576 for s in f if s.startswith("MemAvailable:"))
free = shutil.disk_usage(sys.argv[1]).free / (1024**3)
print(int(mem), int(free))
PY
)
if (( mem_gib < 32 || free_gib < 100 )); then
  echo "BLOCKED: host RAM $mem_gib GiB, disk $free_gib GiB too low" >&2; exit 1
fi
[[ -s "$key" ]] || { echo "BLOCKED: $key missing; copy PUBLIC SSH key only" >&2; exit 1; }
read -r key_type key_data _ < "$key"
[[ "$key_type" == ssh-ed25519 || "$key_type" == ssh-rsa ]] || { echo "BLOCKED: invalid SSH public key"; exit 1; }
[[ "$key_data" =~ ^[A-Za-z0-9+/=]+$ ]] || { echo "BLOCKED: invalid public key data"; exit 1; }
echo "New VM: $vm | 8 vCPU | 16 GiB RAM | 80 GiB disk"
echo "Storage: $pool_dir | NAT: default"
echo "Host MemAvailable: $mem_gib GiB | Disk free: $free_gib GiB"
echo "win11-thunder-rdp and ayush: UNCHANGED"
if [[ "$mode" == --check ]]; then
  echo "READ-ONLY CHECK PASSED; explicit --create required."
  exit 0
fi
[[ "$EUID" == 0 ]] || { echo "Creation requires root on nfc" >&2; exit 1; }
umask 077
mkdir -p "$work"; chmod 700 "$work"
cd "$work"
if [[ ! -f "$image" ]]; then
  curl --fail --location --retry 3 --output "$image.part" "$image_base/$image"
  mv "$image.part" "$image"
fi
curl --fail --location --retry 3 --output SHA256SUMS.part "$image_base/SHA256SUMS"
mv SHA256SUMS.part SHA256SUMS
grep -E '[ *]ubuntu-24[.]04-server-cloudimg-amd64[.]img$' SHA256SUMS | sha256sum --check -
image_format="$(qemu-img info --output=json "$image" | python3 -c 'import json,sys; print(json.load(sys.stdin)["format"])')"
[[ "$image_format" == qcow2 ]] || { echo "Unexpected Ubuntu image format" >&2; exit 1; }
cat > user-data <<EOF
#cloud-config
hostname: mini-ai-inference
manage_etc_hosts: true
users:
  - name: ubuntu
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - "$key_type $key_data"
ssh_pwauth: false
disable_root: true
package_update: false
EOF
cat > meta-data <<EOF
instance-id: mini-ai-inference-1
local-hostname: mini-ai-inference
EOF
qemu-img convert -f qcow2 -O qcow2 "$image" "$disk.part"
qemu-img resize -f qcow2 "$disk.part" 80G
mv "$disk.part" "$disk"
virsh pool-refresh "$pool"
virt-install --connect qemu:///system \
  --name "$vm" --memory 16384 --vcpus 8 --cpu host-model \
  --virt-type kvm --import --osinfo generic \
  --disk "path=$disk,format=qcow2,bus=virtio" \
  --network network=default,model=virtio \
  --cloud-init "user-data=$work/user-data,meta-data=$work/meta-data" \
  --graphics none --console pty,target.type=serial --noautoconsole
echo "New VM requested without autostart."
echo "Check: virsh list --all; virsh net-dhcp-leases default"
