import base64
import hashlib
import hmac
import json
import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${value.hex()}"


def password_ok(password, stored):
    try:
        kind, salt, expected = stored.split("$")
        if kind != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt_key(value, master, session_id):
    nonce = secrets.token_bytes(12)
    data = AESGCM(bytes.fromhex(master)).encrypt(nonce, value.encode(), session_id.encode())
    return base64.b64encode(nonce + data).decode()


def decrypt_key(value, master, session_id):
    raw = base64.b64decode(value)
    return AESGCM(bytes.fromhex(master)).decrypt(raw[:12], raw[12:], session_id.encode()).decode()


def new_ssh_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private = key.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.OpenSSH,
                               serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                         serialization.PublicFormat.OpenSSH).decode()
    return private, public


def guac_data(username, parameters, secret, now=None):
    """Apache Guacamole JSON auth: HMAC + AES-128-CBC, IV=0, PKCS7."""
    key = bytes.fromhex(secret)
    payload = json.dumps({"username": username,
                          "expires": int(((time.time() if now is None else now) + 60) * 1000),
                          "connections": {"Lab terminal": {"protocol": "ssh", "parameters": parameters}}},
                         separators=(",", ":")).encode()
    signed = hmac.new(key, payload, hashlib.sha256).digest() + payload
    padder = padding.PKCS7(128).padder()
    padded = padder.update(signed) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return base64.b64encode(cipher.update(padded) + cipher.finalize()).decode()
