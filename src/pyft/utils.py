import hashlib

from .user_db import users_db


def generate_token(username, password):
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    token = hashlib.sha256(f"{username}{hashed_password}".encode()).hexdigest()
    return token


def validate_token(token):
    for username, hashed_password in users_db.items():
        if token == hashlib.sha256(f"{username}{hashed_password}".encode()).hexdigest():
            return True
    return False
