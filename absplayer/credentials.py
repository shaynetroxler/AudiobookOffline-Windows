from __future__ import annotations

import json
from dataclasses import dataclass

import keyring
import keyring.errors

_SERVICE = "AudiobookOffline"
_USERNAME = "abs-credentials"


@dataclass
class ServerCredentials:
    server_url: str
    username: str
    token: str


def save(creds: ServerCredentials) -> None:
    keyring.set_password(_SERVICE, _USERNAME, json.dumps(creds.__dict__))


def load() -> ServerCredentials | None:
    raw = keyring.get_password(_SERVICE, _USERNAME)
    if raw is None:
        return None
    return ServerCredentials(**json.loads(raw))


def clear() -> None:
    try:
        keyring.delete_password(_SERVICE, _USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
