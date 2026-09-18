# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Sign an exact provider-attestation envelope with an already approved key."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from metriplane.release_control import canonical_json


class EnvelopeSigningError(ValueError):
    """A signing key or Ed25519 operation is unsafe or invalid."""


def sign_envelope(
    private_key_path: Path, *, provider: str, actor_id: str, subject_digest: str
) -> bytes:
    """Return only signature bytes; private key material never enters Python output."""
    if not private_key_path.is_absolute() or not provider or not actor_id:
        raise EnvelopeSigningError("signing identity or key path is invalid")
    try:
        metadata = private_key_path.lstat()
    except OSError as exc:
        raise EnvelopeSigningError("signing key is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise EnvelopeSigningError("signing key is not a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        # Systemd credentials may be protected by an inaccessible 0700 parent
        # rather than 0600 file mode. Its caller verifies that boundary first.
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if not directory or private_key_path.parent != Path(directory):
            raise EnvelopeSigningError("signing key is not inside a private boundary")
    if len(subject_digest) != 64 or any(c not in "0123456789abcdef" for c in subject_digest):
        raise EnvelopeSigningError("signed subject digest is malformed")
    envelope = canonical_json(
        {"actor_id": actor_id, "provider": provider, "subject_digest": subject_digest}
    )
    with tempfile.NamedTemporaryFile(mode="wb", prefix="ed25519-envelope-") as input_file:
        input_file.write(envelope)
        input_file.flush()
        completed = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(private_key_path),
                "-in",
                input_file.name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    if completed.returncode != 0 or len(completed.stdout) != 64:
        raise EnvelopeSigningError("Ed25519 signing failed")
    return completed.stdout
