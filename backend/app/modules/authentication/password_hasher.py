from passlib.context import CryptContext

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_secret(secret: str) -> str:
    return password_context.hash(secret)


def verify_secret(secret: str, hashed_secret: str) -> bool:
    return password_context.verify(secret, hashed_secret)
