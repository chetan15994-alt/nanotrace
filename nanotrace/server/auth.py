"""Cryptographic Authentication & RBAC security engine for NanoTrace Server."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional, Tuple
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from nanotrace.server.models import APIKey, KeyType, Permission, Role, ROLE_PERMISSIONS


API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def generate_api_key(
    workspace_id: str,
    name: str,
    key_type: KeyType = KeyType.INGEST_ONLY,
    project_id: Optional[str] = None,
) -> Tuple[APIKey, str]:
    """Generates a secure cryptographic API key and its raw token.
    
    Returns:
        (APIKey entity to store, raw_token to display ONCE to user).
    """
    prefix = "nt_live_" if key_type == KeyType.INGEST_ONLY else "nt_adm_"
    random_entropy = secrets.token_hex(24)
    raw_key = f"{prefix}{random_entropy}"

    key_prefix = raw_key[:12]
    hashed_secret = hash_secret(raw_key)

    api_key_obj = APIKey(
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        key_prefix=key_prefix,
        hashed_secret=hashed_secret,
        key_type=key_type,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        is_active=True,
    )

    return api_key_obj, raw_key


def hash_secret(secret: str) -> str:
    """Hashes a secret using SHA-256."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Constant-time cryptographic comparison of raw key against stored hash."""
    computed_hash = hash_secret(raw_key)
    return hmac.compare_digest(computed_hash, stored_hash)


def check_permission(user_role: Role, required_permission: Permission) -> bool:
    """Evaluates whether a role possesses the specified permission."""
    allowed_permissions = ROLE_PERMISSIONS.get(user_role, [])
    return required_permission in allowed_permissions


def sign_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    """Generates HMAC-SHA256 signature for outgoing webhook payload verification."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
