import pathlib

from cryptography.fernet import Fernet


def load_or_create_key(key_path: pathlib.Path) -> bytes:
    if key_path.exists():
        return key_path.read_bytes()

    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def encrypt(plaintext: str, key: bytes) -> bytes:
    return Fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes, key: bytes) -> str:
    return Fernet(key).decrypt(token).decode("utf-8")
