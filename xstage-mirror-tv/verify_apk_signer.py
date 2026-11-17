#!/usr/bin/env python3
"""Fail-closed APK signer audit for X-Stage Mirror TV.

Android SDK build-tools 37 reports "V3.0 Signer: certificate SHA-256 digest:"
while earlier apksigner builds use "Signer #1 certificate SHA-256 digest:".
Accept either prefix without loosening the signing-identity check.

Never print or pass signing passwords on the command line.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

CERT_LINE = re.compile(
    r"\bcertificate\s+SHA-256\s+digest\s*:\s*([0-9a-fA-F]{64})\b",
    re.IGNORECASE,
)


def signer_sha256(output: str) -> str:
    values = {match.lower() for match in CERT_LINE.findall(output)}
    if len(values) != 1:
        raise ValueError(
            f"Expected exactly one unique APK signer SHA-256 digest, found {len(values)}. "
            "Refusing to publish an unverifiable or multiply signed APK."
        )
    return values.pop()


def read_verified_apk_signer(apksigner: str, apk: str) -> str:
    result = subprocess.run(
        [apksigner, "verify", "--verbose", "--print-certs", apk],
        check=True,
        capture_output=True,
        text=True,
    )
    return signer_sha256(result.stdout)


def private_keystore_certificate_sha256(keystore: str, alias: str) -> str:
    if not os.environ.get("XSTAGE_MIRROR_STORE_PASSWORD"):
        raise ValueError("Missing XSTAGE_MIRROR_STORE_PASSWORD environment variable")
    result = subprocess.run(
        [
            "keytool", "-exportcert", "-storetype", "PKCS12",
            "-keystore", keystore, "-alias", alias,
            "-storepass:env", "XSTAGE_MIRROR_STORE_PASSWORD",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not result.stdout or result.stdout[0] != 0x30:
        raise ValueError("Could not read a DER-encoded public certificate from the keystore")
    return hashlib.sha256(result.stdout).hexdigest()


def self_test() -> None:
    digest_a = "a" * 64
    digest_b = "b" * 64
    assert signer_sha256(f"Signer #1 certificate SHA-256 digest: {digest_a}\n") == digest_a
    assert signer_sha256(f"V3.0 Signer: certificate SHA-256 digest: {digest_a}\n") == digest_a
    assert signer_sha256(
        f"V2 Signer: certificate SHA-256 digest: {digest_a}\n"
        f"V3.0 Signer: certificate SHA-256 digest: {digest_a}\n"
    ) == digest_a
    for value in (
        "Verified using v3 scheme (APK Signature Scheme v3): true\n",
        f"Signer #1 certificate SHA-256 digest: {digest_a}\n"
        f"Signer #2 certificate SHA-256 digest: {digest_b}\n",
    ):
        try:
            signer_sha256(value)
        except ValueError:
            pass
        else:
            raise AssertionError("Unverifiable or inconsistent signer was accepted")
    print("PASS: APK signer parser accepts old and new SDK output; rejects missing/multiple identities")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", help="APK to verify")
    parser.add_argument("--keystore", help="PKCS12 keystore for signer identity comparison")
    parser.add_argument("--alias", help="Expected keystore key alias")
    parser.add_argument("--apksigner", help="Android SDK apksigner executable")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.apk:
        parser.error("--apk is required unless --self-test is specified")
    if bool(args.keystore) != bool(args.alias):
        parser.error("--keystore and --alias must be provided together")
    apk = Path(args.apk)
    if not apk.is_file() or apk.stat().st_size == 0:
        raise ValueError(f"APK does not exist or is empty: {apk}")
    apksigner = args.apksigner or str(
        Path(os.environ["ANDROID_HOME"]) / "build-tools" / "37.0.0" / "apksigner"
    )
    actual = read_verified_apk_signer(apksigner, str(apk))
    if args.keystore:
        expected = private_keystore_certificate_sha256(args.keystore, args.alias)
        if actual != expected:
            raise ValueError(
                "Verified APK signer does not match the configured persistent keystore. "
                "Never replace or rotate the published signing identity."
            )
    print(actual)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as error:
        print(f"ERROR: X-Stage Mirror TV signature verification failed: {error}", file=sys.stderr)
        sys.exit(1)
