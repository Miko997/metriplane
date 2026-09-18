# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Synthetic OpenSSL key proof; production owner and service keys are absent."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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
