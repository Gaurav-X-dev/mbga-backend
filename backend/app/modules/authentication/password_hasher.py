import bcrypt


def hash_secret(secret: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(secret.encode("utf-8")[:72], salt).decode("utf-8")


def verify_secret(secret: str, hashed_secret: str) -> bool:
    try:
        return bcrypt.checkpw(secret.encode("utf-8")[:72], hashed_secret.encode("utf-8"))
    except Exception:
        return False
