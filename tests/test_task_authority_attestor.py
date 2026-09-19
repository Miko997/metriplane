# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Synthetic OpenSSL key proof; production owner and service keys are absent."""

from __future__ import annotations

import builtins
import subprocess
from pathlib import Path

import pytest

from metriplane import release_control
from metriplane.release_control import ProviderAttestationVerifier
from tools.ed25519_envelope import EnvelopeSigningError
from tools.task_authority_attestor import _sign_attestation


def test_isolated_signer_uses_expected_ed25519_envelope(tmp_path: Path) -> None:
    private_path = tmp_path / "fixture-ed25519.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    public_der = subprocess.check_output(
        ["openssl", "pkey", "-in", str(private_path), "-pubout", "-outform", "DER"],
        stderr=subprocess.DEVNULL,
    )
    assert public_der.startswith(bytes.fromhex("302a300506032b6570032100"))
    assert len(public_der) == 44
    digest = "a" * 64
    signature = _sign_attestation(private_path, subject_digest=digest)
    assert ProviderAttestationVerifier(
        keys={("metriplane-health", "metriplane-health"): public_der[12:]}
    ).verify(
        {
            "provider": "metriplane-health",
            "actor_id": "metriplane-health",
            "signature": signature.hex(),
        },
        subject_digest=digest,
    )
    link = tmp_path / "symlink.pem"
    link.symlink_to(private_path)
    with pytest.raises(EnvelopeSigningError, match="regular file"):
        _sign_attestation(link, subject_digest=digest)


def test_documented_openssl_runtime_verifies_without_python_crypto_or_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_path = tmp_path / "fixture-ed25519.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    public_der = subprocess.check_output(
        ["openssl", "pkey", "-in", str(private_path), "-pubout", "-outform", "DER"],
        stderr=subprocess.DEVNULL,
    )
    digest = "b" * 64
    signature = _sign_attestation(private_path, subject_digest=digest)
    monkeypatch.setattr(release_control, "_verify_ed25519_with_node", lambda *_args: False)
    real_import = builtins.__import__

    def import_without_cryptography(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("cryptography"):
            raise ImportError("fixture removes optional Python crypto")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_cryptography)

    assert ProviderAttestationVerifier(
        keys={("metriplane-health", "metriplane-health"): public_der[12:]}
    ).verify(
        {
            "provider": "metriplane-health",
            "actor_id": "metriplane-health",
            "signature": signature.hex(),
        },
        subject_digest=digest,
    )
    assert not release_control._verify_ed25519_with_openssl(
        public_der[12:],
        b"\x00" * 64,
        b"altered",
    )
