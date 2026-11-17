#!/usr/bin/env bash
# One-time private signing setup for X-Stage Mirror TV.
# Run in a GitHub Codespace / trusted Linux or macOS terminal.
set -Eeuo pipefail
umask 077
REPO="webbase-x/xstage"
ALIAS="xstage-mirror"
KEYSTORE="$HOME/.config/xstage/mirror-tv-release.p12"
if [[ -n "$(printenv XSTAGE_MIRROR_KEYSTORE_PATH 2>/dev/null || true)" ]]; then
  KEYSTORE="$(printenv XSTAGE_MIRROR_KEYSTORE_PATH)"
fi
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in gh keytool python3 base64; do
  command -v "$cmd" >/dev/null 2>&1 || die "Missing $cmd. Use a Codespace with GitHub CLI and JDK 21."
done
# Codespaces exposes a repository-scoped GITHUB_TOKEN. GitHub CLI gives
# GH_TOKEN/GITHUB_TOKEN priority over a personal OAuth login, so the automatic
# Codespaces token may be able to push code but not manage Actions Secrets.
# Prefer a verified, separately authorized login when the env token is limited.
gh auth status -h github.com >/dev/null 2>&1 ||
  die "GitHub CLI is not authenticated. Sign in as the repository owner."
GH=(gh)
if ! "${GH[@]}" api "repos/$REPO/actions/secrets/public-key" -q '.key' >/dev/null 2>&1; then
  if { [[ -n "${GH_TOKEN:-}" ]] || [[ -n "${GITHUB_TOKEN:-}" ]]; } &&
      env -u GH_TOKEN -u GITHUB_TOKEN gh api "repos/$REPO/actions/secrets/public-key" -q '.key' >/dev/null 2>&1; then
    GH=(env -u GH_TOKEN -u GITHUB_TOKEN gh)
    printf 'Using authorized personal GitHub CLI login instead of restricted Codespaces token.\n'
  else
    printf >&2 '\nGitHub Codespaces may be masking your repository-owner login with its restricted GITHUB_TOKEN.\n'
    printf >&2 'Run this in the Codespaces terminal (do NOT paste tokens into chat):\n'
    printf >&2 '  env -u GH_TOKEN -u GITHUB_TOKEN gh auth login --web --hostname github.com --scopes repo\n'
    printf >&2 '  env -u GH_TOKEN -u GITHUB_TOKEN gh api repos/%s/actions/secrets/public-key --jq .key_id\n' "$REPO"
    printf >&2 'Then rerun this script. If the public-key request still fails, configure Actions Secrets from the repository Settings page, or check repository permissions.\n'
    die "No GitHub credential with Actions Secrets access for $REPO."
  fi
fi

# A public fingerprint pin is not a private key. Never rotate it accidentally.
PIN="$(python3 - "$ROOT" <<'PY'
import json,pathlib,sys
root=pathlib.Path(sys.argv[1])
pins=set()
for name in ("mirror-tv/latest.json","mirror-tv/test-latest.json"):
    p=root/name
    if p.is_file():
        item=json.loads(p.read_text(encoding="utf-8"))
        if item.get("signing_mode")=="persistent":
            value=item.get("signer_sha256","").lower()
            if len(value)!=64 or any(ch not in "0123456789abcdef" for ch in value):
                raise SystemExit("Malformed published signer pin")
            pins.add(value)
if len(pins)>1: raise SystemExit("Published preview/production signing identities conflict")
print(next(iter(pins),""))
PY
)"
if [[ ! -f "$KEYSTORE" ]]; then
  if "${GH[@]}" secret list -R "$REPO" | grep -Eq '^XSTAGE_MIRROR_KEYSTORE_BASE64[[:space:]]'; then
    die "A private keystore already exists in GitHub Secrets. Restore its ORIGINAL file; never generate a replacement."
  fi
  [[ -z "$PIN" ]] || die "A signer is already published ($PIN). Restore the original private keystore."
  printf '\nFirst-time X-Stage Mirror TV signing\n'
  printf 'A NEW private key will be created at %s\n' "$KEYSTORE"
  printf 'A legacy debug-signed Build 107 CANNOT update in place using a new key.\n'
  printf 'Back up this keystore and its password securely. Losing them prevents future updates.\n'
  read -r -p "Type CREATE to generate a NEW permanent key: " reply
  [[ "$reply" == "CREATE" ]] || die "Cancelled; existing APK and settings remain unchanged."
  mkdir -p "$(dirname "$KEYSTORE")"
  XSTAGE_MIRROR_SETUP_PASSWORD="$(python3 - <<'PY'
import secrets,string
alphabet=string.ascii_letters+string.digits
print("".join(secrets.choice(alphabet) for _ in range(48)))
PY
)"
  export XSTAGE_MIRROR_SETUP_PASSWORD
  printf '\nSTORE THIS PASSWORD IN A PRIVATE PASSWORD MANAGER (shown once):\n%s\n\n' "$XSTAGE_MIRROR_SETUP_PASSWORD"
  read -r -p "Type SAVED after you have securely stored the password: " reply
  [[ "$reply" == "SAVED" ]] || die "Cancelled before generating the key."
  keytool -genkeypair -noprompt -storetype PKCS12 -keystore "$KEYSTORE" \
    -alias "$ALIAS" -keyalg RSA -keysize 3072 -sigalg SHA256withRSA \
    -validity 10000 -dname "CN=X-Stage Mirror TV, OU=Android TV, O=Webbase-X, C=TH" \
    -storepass:env XSTAGE_MIRROR_SETUP_PASSWORD \
    -keypass:env XSTAGE_MIRROR_SETUP_PASSWORD >/dev/null
  chmod 600 "$KEYSTORE"
else
  printf 'Reusing existing keystore: %s\n' "$KEYSTORE"
  read -r -s -p "Existing keystore password: " XSTAGE_MIRROR_SETUP_PASSWORD
  printf '\n'
  export XSTAGE_MIRROR_SETUP_PASSWORD
fi
trap 'unset XSTAGE_MIRROR_SETUP_PASSWORD' EXIT

CERT_INFO="$(keytool -list -v -storetype PKCS12 -keystore "$KEYSTORE" \
  -alias "$ALIAS" -storepass:env XSTAGE_MIRROR_SETUP_PASSWORD)" ||
    die "Cannot read the keystore; verify password and alias."
FINGERPRINT="$(printf '%s\n' "$CERT_INFO" | python3 -c '
import re,sys
m=re.search(r"SHA256:\s*([0-9a-fA-F:]{64,95})",sys.stdin.read())
if not m: raise SystemExit("Certificate SHA-256 not found")
print(m.group(1).replace(":","").lower())
')"
[[ "$FINGERPRINT" =~ ^[0-9a-f]{64}$ ]] || die "Invalid certificate fingerprint"
[[ -z "$PIN" || "$PIN" == "$FINGERPRINT" ]] ||
  die "Signer differs from pinned identity ($PIN). Refusing key rotation."
printf 'Verified signing certificate SHA-256: %s\n' "$FINGERPRINT"

# gh encrypts stdin locally before publishing to GitHub Actions secrets.
base64 < "$KEYSTORE" | tr -d '\r\n' | "${GH[@]}" secret set XSTAGE_MIRROR_KEYSTORE_BASE64 -R "$REPO"
printf '%s' "$XSTAGE_MIRROR_SETUP_PASSWORD" | "${GH[@]}" secret set XSTAGE_MIRROR_STORE_PASSWORD -R "$REPO"
printf '%s' "$ALIAS" | "${GH[@]}" secret set XSTAGE_MIRROR_KEY_ALIAS -R "$REPO"
printf '%s' "$XSTAGE_MIRROR_SETUP_PASSWORD" | "${GH[@]}" secret set XSTAGE_MIRROR_KEY_PASSWORD -R "$REPO"
printf '\nAll four encrypted GitHub Secrets uploaded.\n'
printf 'BACK UP this keystore outside the repository AND Codespace: %s\n' "$KEYSTORE"
printf 'Do not share the keystore or password.\n'

if "${GH[@]}" workflow run build-xstage-mirror-tv.yml -R "$REPO" --ref main; then
  printf 'Signed Build requested: https://github.com/%s/actions/workflows/build-xstage-mirror-tv.yml\n' "$REPO"
else
  printf 'Secrets saved. Start the Build manually from GitHub Actions:\n'
  printf 'https://github.com/%s/actions/workflows/build-xstage-mirror-tv.yml\n' "$REPO"
fi
