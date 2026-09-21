import pytest
from mail_organizer.crypto import load_or_create_key, encrypt, decrypt


def test_load_or_create_key_creates_file_on_first_use(tmp_path):
    key_path = tmp_path / "secret.key"
    assert not key_path.exists()

    key = load_or_create_key(key_path)

    assert key_path.exists()
    assert len(key) > 0


def test_load_or_create_key_reuses_existing_key(tmp_path):
    key_path = tmp_path / "secret.key"
    first = load_or_create_key(key_path)
    second = load_or_create_key(key_path)

    assert first == second


def test_encrypt_decrypt_roundtrip(tmp_path):
    key = load_or_create_key(tmp_path / "secret.key")

    token = encrypt("super-secret-token", key)
    result = decrypt(token, key)

    assert result == "super-secret-token"
    assert token != b"super-secret-token"


def test_decrypt_fails_with_wrong_key(tmp_path):
    key_a = load_or_create_key(tmp_path / "a.key")
    key_b = load_or_create_key(tmp_path / "b.key")
    token = encrypt("secret", key_a)

    with pytest.raises(Exception):
        decrypt(token, key_b)
