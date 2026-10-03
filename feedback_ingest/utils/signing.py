import hashlib
import hmac


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    # replace: a lone surrogate in the header compares unequal instead of raising
    return hmac.compare_digest(sign(secret, body).encode(), signature.encode(errors="replace"))
