# Mini AI Phase 1B — New isolated libvirt VM on NFC

Updated: 2026-11-07. **Preparation only:** no commands in this document have been executed on NFC by ChatGPT. Run the read-only preflight first. The provisioning section **creates and boots a NEW VM**, so the owner should review it before running on the host. Do not modify existing VMs.

## Verified host facts

- Host: `nfc`, Ubuntu 24.04.4, 40 logical Xeon Gold 6138 threads / 20 physical cores, one NUMA node, ~80 GiB RAM available, 732 GB SSD available; no NVIDIA GPU detected.
- libvirt URI: `qemu:///system`, libvirt storage pools `images`, `thunder` and `win11-thunder-rdp` active; `default` virtual network active; `virt-install` present. `cloud-localds` not found.
- `win11-thunder-rdp`: **running**, 8 vCPUs, 32 GiB guest allocation. `ayush`: **shut off**, 4 vCPUs, 8 GiB allocation, unrelated to Mini AI.
- cgroup v2 and systemd 255 available; the host is used for active workloads.
- Two tiny QEMU processes were also visible beyond the main Windows VM. Do not kill them, and do not assume they are separate domains.

**Preferred VM:** `mini-ai-inference`, initially 8 vCPUs, 16 GiB RAM, 80 GiB dynamically allocated qcow2 disk, Ubuntu 24.04 cloud image, NAT attached to existing `default` libvirt network. No GPU, no bridge/public IP and no VM autostart initially.

## 1. Safe read-only host checks

You may run these from `root@nfc` as-is:

~~~bash
virsh -c qemu:///system pool-info images
virsh -c qemu:///system net-info default
virsh -c qemu:///system pool-dumpxml images | grep '<path>'
command -v qemu-img
virsh -c qemu:///system dominfo mini-ai-inference || true
free -h
df -h /
~~~

The non-destructive helper is tracked at [scripts/nfc_vm_preflight.sh](../scripts/nfc_vm_preflight.sh). It checks the exact storage pool path and refuses a VM name collision:

~~~bash
# On NFC after reviewing the script in GitHub; clone only if wanted:
git clone https://github.com/getkcoin-alt/mini-ai.git /root/mini-ai
cd /root/mini-ai
bash scripts/nfc_vm_preflight.sh
~~~

If `/root/mini-ai` already exists, use `git -C /root/mini-ai pull --ff-only origin main` instead.

**Do not continue to provisioning** if the `images` pool path is missing, the `mini-ai-inference` name already exists, the VM network is not active, `qemu-img` is unavailable, or the host does not have spare resources.

## 2. Prepare a unique SSH public key (on Mac)

Generate a dedicated key **only if one does not already exist**:

~~~bash
test -f "$HOME/.ssh/id_ed25519.pub" || ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -C "mini-ai-operator"
~~~

Transfer **the .pub public key only** to NFC, substituting the SSH hostname:

~~~bash
scp "$HOME/.ssh/id_ed25519.pub" root@NFC_SSH_HOST:/root/mini-ai-operator.pub
~~~

Never upload private keys, API tokens, VM disk images or cloned voice recordings into GitHub or this chat.

## 3. After approving provisioning: download and check Ubuntu image

Use Ubuntu's **released** 24.04 LTS amd64 cloud image, not the changing daily image. The checksum is downloaded from the same released-image directory.

On `nfc`:

~~~bash
set -euo pipefail
mkdir -p -m 700 /root/mini-ai-provision
cd /root/mini-ai-provision
BASE='https://cloud-images.ubuntu.com/releases/noble/release'
curl -fL "$BASE/ubuntu-24.04-server-cloudimg-amd64.img" -o ubuntu-24.04-server-cloudimg-amd64.img
curl -fL "$BASE/SHA256SUMS" -o SHA256SUMS
grep -E '[ *]ubuntu-24[.]04-server-cloudimg-amd64[.]img$' SHA256SUMS | sha256sum -c -
~~~

If the checksum fails, **stop**. Do not build a VM from an unverified download. More rigorous production supply-chain validation can additionally verify the signed checksum file using Canonical's signing key.

## 4. Create one new private guest (writes only new VM resources)

**Do not run until the read-only preflight and SSH public key checks pass.** These commands intentionally avoid the running Windows VM, the shutdown `ayush` VM, any existing disk image, host bridges, and host firewall.

~~~bash
set -euo pipefail
VM=mini-ai-inference
POOL=images
BASE_DIR=/root/mini-ai-provision
POOL_DIR="$(virsh -c qemu:///system pool-dumpxml "$POOL" |
  python3 -c "import sys,xml.etree.ElementTree as E; print(E.parse(sys.stdin).findtext('./target/path') or '')")"
test -n "$POOL_DIR" && test -d "$POOL_DIR"
! virsh -c qemu:///system dominfo "$VM" >/dev/null 2>&1
test -f "$BASE_DIR/ubuntu-24.04-server-cloudimg-amd64.img"
test -f /root/mini-ai-operator.pub
grep -Eq '^(ssh-ed25519|ssh-rsa) ' /root/mini-ai-operator.pub
VM_DISK="$POOL_DIR/$VM.qcow2"
test ! -e "$VM_DISK"

# This copies only the official verified base image into a new guest disk.
qemu-img convert -f qcow2 -O qcow2 \
  "$BASE_DIR/ubuntu-24.04-server-cloudimg-amd64.img" "$VM_DISK"
qemu-img resize "$VM_DISK" 80G
virsh -c qemu:///system pool-refresh "$POOL"

# Cloud-init guest account: key-only SSH, disabled root SSH and password login.
OPERATOR_PUBKEY="$(cat /root/mini-ai-operator.pub)"
umask 077
cat > "$BASE_DIR/user-data" <<EOF
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
      - "$OPERATOR_PUBKEY"
ssh_pwauth: false
disable_root: true
package_update: true
packages:
  - qemu-guest-agent
EOF
cat > "$BASE_DIR/meta-data" <<EOF
instance-id: mini-ai-inference-first
local-hostname: mini-ai-inference
EOF

virt-install \
  --connect qemu:///system \
  --name "$VM" \
  --memory 16384 \
  --vcpus 8 \
  --virt-type kvm \
  --import \
  --osinfo generic \
  --disk "path=$VM_DISK,format=qcow2,bus=virtio" \
  --network network=default,model=virtio \
  --cloud-init "user-data=$BASE_DIR/user-data,meta-data=$BASE_DIR/meta-data" \
  --graphics none \
  --console pty,target.type=serial \
  --noautoconsole
~~~

**Provisioning caveats:** the guest image must be readable by the libvirt QEMU service from the selected pool, and libvirt/AppArmor must permit access; stop and inspect any permission or launch error rather than disabling AppArmor or changing VM pool permissions indiscriminately. The `--cloud-init` option is supported by Ubuntu's packaged `virt-install` but might require helper packages. Do not run a blind `apt upgrade` on the long-running virtualization host to solve such errors.

The guest is not configured to autostart until it has passed tests.

**Important:** because some recent versions of virt-install have had issues with cloud-init user-data without meta-data, the command explicitly supplies **both**. Check actual guest SSH onboarding before proceeding.

## 5. Verify the new guest without touching existing VMs

~~~bash
virsh -c qemu:///system list --all
virsh -c qemu:///system dominfo mini-ai-inference
virsh -c qemu:///system net-dhcp-leases default
virsh -c qemu:///system domifaddr mini-ai-inference --source lease
~~~

SSH into the new NAT guest from the `nfc` host using its DHCP address:

~~~bash
ssh -i /root/.ssh/id_ed25519 ubuntu@GUEST_PRIVATE_IP
~~~

If that private key is **only on the Mac**, connect using a jump host from the Mac rather than putting the key on `nfc`:

~~~bash
ssh -J root@NFC_SSH_HOST ubuntu@GUEST_PRIVATE_IP
~~~

Do not open VM SSH directly to the public internet. Ensure the public key provided in cloud-init matches the **private key used by the SSH client**.

## 6. Install and benchmark Mini only INSIDE the new VM

Run these after logging into the guest as `ubuntu`:

~~~bash
git clone https://github.com/getkcoin-alt/mini-ai.git ~/mini-ai
cd ~/mini-ai
# Review the install script first; it installs packages in the new guest.
sed -n '1,200p' services/voice_worker/setup_cpu_ubuntu.sh
sudo bash services/voice_worker/setup_cpu_ubuntu.sh
~~~

Install the authorized Friend and Mentor voice samples into the guest's own `~/.mini-ai/voice` directory, not onto the libvirt host. Since the installer currently uses the shell user's home directory, check `HOME` when running with sudo; on this guest, run the voice-reference installation as the `ubuntu` user with Python 3, rather than sudo.

Benchmark Nano at 8 guest vCPUs first and compare with the previously measured warm `scrizaone` results (~11–13 seconds for short text-to-voice turns). Do not assume that the VM with more host RAM is automatically faster.

## 7. Never change the working production route until tested

- `win11-thunder-rdp` and `ayush` must remain untouched.
- `scrizaone` stays the already-proven Mini AI voice fallback.
- No external HTTP/S traffic is sent to the guest until a secure service-to-service HTTPS gateway is designed.
- No Mini voice recordings, private keys, or auth tokens enter public GitHub.
- Measure VM impact and start with single-turn concurrency. Voice remains turn-based; not streaming full-duplex yet.

### Verified documentation

- Ubuntu's official cloud image/libvirt guide: https://ubuntu.com/docs/public-images/public-images-how-to/launch-with-libvirt/
- Ubuntu 24.04 `virt-install` manpage: https://manpages.ubuntu.com/manpages/noble/man1/virt-install.1.html
- Canonical released Ubuntu images: https://cloud-images.ubuntu.com/releases/noble/release/
- libvirt `virsh` reference: https://www.libvirt.org/manpages/virsh.html
