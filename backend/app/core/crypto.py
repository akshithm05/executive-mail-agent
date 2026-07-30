"""Symmetric encryption for secrets at rest.

Google OAuth access/refresh tokens are the highest-value secrets this service
holds: anyone who obtains a refresh token can read the tenant's mailbox
indefinitely. They are therefore never written to the database in plaintext.
:class:`TokenCipher` wraps :mod:`cryptography`'s Fernet (AES-128-CBC + HMAC,
authenticated encryption) so callers work with plain strings while the
ciphertext-at-rest guarantee is enforced in one place.
"""

from __future__ import annotations

from http import HTTPStatus

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import AppError


class TokenDecryptionError(AppError):
    """A stored secret could not be decrypted.

    This indicates the encryption key has changed (e.g. rotated without
    re-encrypting existing rows) or the ciphertext was tampered with /
    corrupted. Either way, the caller cannot recover the plaintext and must
    force reauthentication rather than proceed with a broken credential.
    """

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "token_decryption_failed"
    message = "A stored credential could not be decrypted."


class TokenCipher:
    """Encrypts and decrypts secrets using a Fernet symmetric key.

    Args:
        key: A 32-byte, url-safe base64-encoded Fernet key.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext secret, returning an opaque ciphertext string."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext previously produced by :meth:`encrypt`.

        Raises:
            TokenDecryptionError: If the ciphertext is invalid, corrupted, or
                was encrypted with a different key.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenDecryptionError() from exc
