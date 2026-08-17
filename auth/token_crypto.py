"""
auth/token_crypto.py — the encryption boundary for provider bearer material.

WHAT THIS OWNS. Turning a Yahoo access or refresh token into something safe to
put in a database column, and back again. It owns no schema, no session, no
provider and no policy about WHEN a token is stored — only how, so that there is
exactly one place in the product where bearer material meets storage.

WHY IT EXISTS AT ALL. A Yahoo refresh token is a long-lived credential: anyone
holding one can mint access tokens for that user's Yahoo Fantasy data until the
user revokes it from their Yahoo account settings. A database backup, a replica,
a support query or a leaked dump would otherwise hand that credential over in
readable form. Encrypting it moves the secret out of the database and into the
deployment's key management, which is where a secret belongs.

── THE CONSTRUCTION, AND WHY EACH PART IS THERE ─────────────────────────────

    AES-256-GCM              authenticated encryption. Confidentiality AND
                             integrity: a ciphertext that has been altered by
                             one bit fails to open rather than decrypting to
                             something else. `cryptography` is already a pinned
                             dependency of this project, so this is the standard
                             primitive rather than anything invented here.

    96-bit random nonce      fresh per encryption, from `secrets`. GCM's one
                             absolute rule is that a (key, nonce) pair is never
                             reused; a random 96-bit nonce is the construction
                             NIST SP 800-38D names for exactly this case, and
                             the nonce travels with the ciphertext because it is
                             not secret.

    ASSOCIATED DATA          the ciphertext is bound to the ROW it belongs to.
                             This is not decoration. Without it, a ciphertext
                             copied from user A's row into user B's row would
                             decrypt perfectly, and user B's provider reads
                             would run on user A's Yahoo grant — the precise
                             failure the per-user architecture exists to
                             prevent. With it, the copy fails to open.

    VERSIONED ENVELOPE       every value carries its format version and the id
                             of the key that sealed it, in the clear. That is
                             what makes rotation possible without a migration:
                             a new key is added, new writes use it, old values
                             keep naming the old key and keep opening.

── WHAT IS DELIBERATELY NOT HERE ────────────────────────────────────────────

NO KEY IN THE DATABASE, and no default key. Key material comes from the
environment; if none is configured, this module REFUSES rather than falling back
to storing anything readable. A fallback would mean the one deployment that
forgot to set a key is the one that stores every refresh token in plaintext, and
nothing would say so.

NO ENCRYPTION OF YAHOO FANTASY INFORMATION. This module is for OAuth
credentials. Fantasy payloads are not stored by this product at all, encrypted
or otherwise — see the storage boundary in `auth/provider_grant.py`.

NO SECRET IN A REPR, A LOG OR AN EXCEPTION. Every error raised here names what
went wrong structurally and never includes the value it was working on.
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass

__all__ = [
    "ENVELOPE_VERSION",
    "KEY_ENV",
    "KEY_ENV_PREFIX",
    "TokenCryptoError",
    "TokenCryptoUnavailable",
    "available",
    "decrypt",
    "encrypt",
    "generate_key",
    "load_keyring",
]

#: The envelope format. Bumped only if the construction changes; the version
#: rides in every stored value so old rows stay readable.
ENVELOPE_VERSION = "v1"

#: The active key. Base64 (standard or urlsafe) of exactly 32 bytes.
KEY_ENV = "FS_TOKEN_ENCRYPTION_KEY"

#: Retired keys, still needed to OPEN values sealed before a rotation:
#: `FS_TOKEN_ENCRYPTION_KEY_<id>`. The active key's id is `FS_TOKEN_KEY_ID`, or
#: `active` when unset.
KEY_ENV_PREFIX = "FS_TOKEN_ENCRYPTION_KEY_"

_KEY_ID_ENV = "FS_TOKEN_KEY_ID"
_DEFAULT_KEY_ID = "active"

_NONCE_BYTES = 12          # 96 bits — the width GCM is specified for
_KEY_BYTES = 32            # AES-256


class TokenCryptoError(Exception):
    """A value could not be sealed or opened.

    NEVER CARRIES THE VALUE. The message describes the failure structurally so
    it can be logged; the plaintext and the ciphertext both stay out of it.
    """


class TokenCryptoUnavailable(TokenCryptoError):
    """No usable key material is configured.

    A DISTINCT TYPE ON PURPOSE. "This deployment has not been given a key" is an
    operator condition with an operator remedy, and callers map it to a
    configuration error rather than to a corrupt-token error.
    """


@dataclass(frozen=True)
class _Keyring:
    """The active key, plus any retired keys still needed for reads."""

    active_id: str
    keys: dict          # key_id -> 32 raw bytes

    def __repr__(self) -> str:            # pragma: no cover - defensive
        # NEVER REPR THE KEYS. This object appears in tracebacks.
        return (f"_Keyring(active_id={self.active_id!r}, "
                f"key_ids={sorted(self.keys)!r}, material=<hidden>)")


def _decode_key(raw: str, *, name: str) -> bytes:
    text = (raw or "").strip()
    if not text:
        raise TokenCryptoUnavailable(f"{name} is empty")
    padded = text + "=" * (-len(text) % 4)
    try:
        material = base64.urlsafe_b64decode(padded)
    except Exception:
        try:
            material = base64.b64decode(padded)
        except Exception as exc:
            raise TokenCryptoError(f"{name} is not valid base64") from exc
    if len(material) != _KEY_BYTES:
        # STATED IN BYTES, NOT SHOWN. A key of the wrong length is a
        # configuration mistake and the operator needs the number, not the value.
        raise TokenCryptoError(
            f"{name} must decode to {_KEY_BYTES} bytes, got {len(material)}")
    return material


def load_keyring(environ: dict | None = None) -> _Keyring:
    """Assemble the keyring from the environment, or refuse.

    THE ACTIVE KEY IS REQUIRED; retired keys are optional and read-only. A
    deployment mid-rotation has both, and every stored value names which one
    sealed it, so both work at once with no migration and no downtime.
    """
    env = os.environ if environ is None else environ

    keys: dict[str, bytes] = {}
    for name, value in env.items():
        if not name.startswith(KEY_ENV_PREFIX):
            continue
        key_id = name[len(KEY_ENV_PREFIX):].strip().lower()
        if not key_id:
            continue
        keys[key_id] = _decode_key(value, name=name)

    active_id = (env.get(_KEY_ID_ENV, "") or "").strip().lower() or _DEFAULT_KEY_ID
    active_raw = env.get(KEY_ENV, "")
    if active_raw:
        keys[active_id] = _decode_key(active_raw, name=KEY_ENV)
    elif active_id not in keys:
        raise TokenCryptoUnavailable(
            f"{KEY_ENV} is not set. Provider tokens cannot be stored without "
            f"application-level encryption, and this module will not fall back "
            f"to storing them readable. Generate one with "
            f"`python -c \"from auth.token_crypto import generate_key; "
            f"print(generate_key())\"` and set it in the deployment environment.")

    return _Keyring(active_id=active_id, keys=keys)


def available(environ: dict | None = None) -> bool:
    """Whether this deployment can store provider tokens at all.

    Used by configuration surfaces to report a missing key as a deployment
    condition BEFORE a user reaches a sign-in that would then fail halfway.
    """
    try:
        load_keyring(environ)
        return True
    except TokenCryptoError:
        return False


def generate_key() -> str:
    """A fresh 256-bit key, base64url, for an operator to put in the environment.

    NOT CALLED BY THE APPLICATION. It exists so nobody has to invent a key by
    hand, or reach for a password.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(_KEY_BYTES)).decode()


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:            # pragma: no cover - pinned dependency
        raise TokenCryptoUnavailable(
            "the `cryptography` package is required to store provider tokens"
        ) from exc
    return AESGCM(key)


def _aad(context: str) -> bytes:
    """The associated data a ciphertext is bound to.

    The caller passes something that identifies the ROW and the FIELD — see the
    module docstring for why moving a ciphertext between rows has to fail.
    """
    if not context or not str(context).strip():
        raise TokenCryptoError("an encryption context is required")
    return f"{ENVELOPE_VERSION}|{context}".encode("utf-8")


def encrypt(plaintext: str, *, context: str,
            environ: dict | None = None) -> str:
    """Seal a token for storage.

    :param plaintext: the bearer material. Never logged, never returned.
    :param context:   what this value belongs to, e.g. ``"grant:41:refresh"``.
                      It is authenticated but not secret, and it must be
                      reproducible at read time.
    :returns: ``v1.<key_id>.<nonce>.<ciphertext>``, all base64url, safe for a
              text column and self-describing for rotation.
    """
    if plaintext is None or plaintext == "":
        raise TokenCryptoError("refusing to encrypt an empty value")
    keyring = load_keyring(environ)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    sealed = _aesgcm(keyring.keys[keyring.active_id]).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(context))
    return ".".join([
        ENVELOPE_VERSION,
        keyring.active_id,
        base64.urlsafe_b64encode(nonce).decode().rstrip("="),
        base64.urlsafe_b64encode(sealed).decode().rstrip("="),
    ])


def decrypt(envelope: str, *, context: str,
            environ: dict | None = None) -> str:
    """Open a stored token.

    RAISES RATHER THAN RETURNING A GUESS. A value that fails to open has either
    been tampered with, been moved to a row it does not belong to, or been
    sealed with a key this deployment no longer has — and every one of those is
    a condition the caller must handle as "this grant is unusable", not as an
    empty string it might pass to Yahoo.
    """
    parts = (envelope or "").split(".")
    if len(parts) != 4:
        raise TokenCryptoError("stored token is not a valid envelope")
    version, key_id, nonce_b64, sealed_b64 = parts
    if version != ENVELOPE_VERSION:
        raise TokenCryptoError(f"unsupported envelope version {version!r}")

    keyring = load_keyring(environ)
    key = keyring.keys.get(key_id.strip().lower())
    if key is None:
        # THE KEY IS GONE, NOT THE TOKEN. Naming which key is missing is what
        # lets an operator restore it; the token itself stays sealed.
        raise TokenCryptoError(
            f"no key {key_id!r} is configured; the value was sealed with a key "
            f"this deployment does not currently hold")

    def _b64(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    try:
        opened = _aesgcm(key).decrypt(_b64(nonce_b64), _b64(sealed_b64),
                                      _aad(context))
    except TokenCryptoError:
        raise
    except Exception as exc:
        # `InvalidTag` and every decoding failure land here and are reported the
        # same way ON PURPOSE: distinguishing "wrong key" from "tampered" from
        # "wrong row" for a caller would be telling an attacker which of those
        # they achieved.
        raise TokenCryptoError("stored token failed authentication") from exc
    return opened.decode("utf-8")
