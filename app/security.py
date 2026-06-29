"""Parol hashlash — bcrypt to'g'ridan-to'g'ri ishlatiladi."""
import bcrypt


def hash_password(plain: str) -> str:
    """Ochiq parolni bcrypt hashga aylantiradi."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Kiritilgan parol hashga mosligini tekshiradi."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
