"""Tests for token encryption at rest."""

import pytest
from app.core.crypto import TokenCipher, TokenDecryptionError
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    plaintext = "ya29.super-secret-google-access-token"

    ciphertext = cipher.encrypt(plaintext)

    assert ciphertext != plaintext
    assert cipher.decrypt(ciphertext) == plaintext


def test_ciphertext_is_not_plaintext_substring() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    plaintext = "refresh-token-value-12345"

    ciphertext = cipher.encrypt(plaintext)

    assert plaintext not in ciphertext


def test_decrypt_with_wrong_key_raises() -> None:
    cipher_a = TokenCipher(Fernet.generate_key().decode())
    cipher_b = TokenCipher(Fernet.generate_key().decode())
    ciphertext = cipher_a.encrypt("some-secret")

    with pytest.raises(TokenDecryptionError):
        cipher_b.decrypt(ciphertext)


def test_decrypt_corrupted_ciphertext_raises() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())

    with pytest.raises(TokenDecryptionError):
        cipher.decrypt("not-a-valid-fernet-token")
