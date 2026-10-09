#!/usr/bin/env bash
# Install a pinned, stable Foundry into the project (.tools/foundry/bin), see DECISIONS D-030.
#
# Deliberately does NOT use foundryup: it only downloads the release tarball and
# unpacks it here. It never writes to ~/.foundry (where the owner keeps
# foundry-zksync for another project) and never edits shell profiles.
set -euo pipefail

VERSION="v1.4.4"   # same version as the stable anvil already on this machine
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.tools/foundry/bin"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  PLATFORM="darwin_arm64" ;;
  Darwin-x86_64) PLATFORM="darwin_amd64" ;;
  Linux-x86_64)  PLATFORM="linux_amd64" ;;
  Linux-aarch64) PLATFORM="linux_arm64" ;;
  *) echo "unsupported platform $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

URL="https://github.com/foundry-rs/foundry/releases/download/${VERSION}/foundry_${VERSION}_${PLATFORM}.tar.gz"
mkdir -p "$DEST"
echo "downloading $URL"
curl -fsSL "$URL" | tar -xz -C "$DEST"
"$DEST/forge" --version | head -1
