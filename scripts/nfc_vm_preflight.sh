#!/usr/bin/env bash
# READ-ONLY host preparation report for a prospective Mini AI VM.
# Safe to run on the nfc KVM/libvirt host; does not install, allocate or start anything.
set -euo pipefail
VM_NAME="mini-ai-inference"
POOL_NAME="images"
NET_NAME="default"
echo "MINI AI — NFC LIBVIRT READ-ONLY PREFLIGHT"
echo "Libvirt connection: $(virsh uri)"
printf '\nExisting VMs:\n'
virsh -c qemu:///system list --all
printf '\nStorage pool details:\n'
virsh -c qemu:///system pool-info "$POOL_NAME"
POOL_PATH="$(virsh -c qemu:///system pool-dumpxml "$POOL_NAME" | python3 -c "import xml.etree.ElementTree as E,sys; print(E.parse(sys.stdin).findtext('./target/path') or '')")"
if [[ -z "$POOL_PATH" || ! -d "$POOL_PATH" ]]; then
  echo "BLOCKED: images storage pool path could not be resolved." >&2
  exit 1
fi
echo "images pool path: $POOL_PATH"
df -h "$POOL_PATH"
printf '\nDefault network:\n'
virsh -c qemu:///system net-info "$NET_NAME"
printf '\nVM name collision check:\n'
if virsh -c qemu:///system dominfo "$VM_NAME" >/dev/null 2>&1; then
  echo "BLOCKED: $VM_NAME already exists. Never overwrite or reuse it." >&2
  exit 2
else
  echo "$VM_NAME does not exist: name available."
fi
printf '\nHost hardware and resource headroom:\n'
nproc
free -h
df -h /
printf '\nRequired tools:\n'
for tool in virt-install qemu-img curl sha256sum python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "$tool: available"
  else
    echo "$tool: missing"
  fi
done
if command -v cloud-localds >/dev/null 2>&1; then
  echo "cloud-localds: available"
else
  echo "cloud-localds: not installed (virt-install may still support --cloud-init)"
fi
printf '\nVM and network state unchanged. Do not share private SSH keys or VM XML.\n'
