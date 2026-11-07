#!/usr/bin/env bash
# Build the private Mini UI inside mini-ai-inference without changing Ubuntu's system Node.
# A pinned official Node.js binary is checksum-verified before execution.
set -Eeuo pipefail
[[ "$(hostname -s)" == mini-ai-inference ]] || { echo "Run only in the Mini guest"; exit 2; }
[[ "$EUID" == 0 ]] || { echo "Use sudo inside the Mini guest"; exit 2; }
[[ -d /opt/mini-ai && -f /opt/mini-ai/package.json ]] || {
  echo "Install the Mini guest worker first"; exit 1;
}
command -v curl >/dev/null || { echo "curl is required (install it inside this guest)"; exit 1; }
command -v tar >/dev/null || { echo "tar is required"; exit 1; }
version="v22.16.0"
archive="node-$version-linux-x64.tar.xz"
expected="f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e"
directory="/opt/mini-node"
bin="$directory/node-$version-linux-x64/bin"
mkdir -p "$directory"
if [[ ! -x "$bin/node" ]]; then
  cd "$directory"
  curl --fail --location --retry 3 \
    "https://nodejs.org/dist/$version/$archive" -o "$archive.part"
  mv "$archive.part" "$archive"
  echo "$expected  $archive" | sha256sum --check -
  tar -xJf "$archive" -C "$directory"
fi
export PATH="$bin:$PATH"
node --version
npm --version
cd /opt/mini-ai
npm install --no-audit --no-fund
npm test
npm run build
[[ -s /opt/mini-ai/dist/index.html ]] || { echo "No built index.html"; exit 1; }
echo "Private frontend built at /opt/mini-ai/dist"
echo "If Mini worker is running, restart its service in the guest to mount the new static files."
