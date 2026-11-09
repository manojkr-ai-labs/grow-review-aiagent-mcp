"""Case, run, and execution ids.

Ids are random. They never embed message text, and the helpers here do not
read or write case content.
"""

from __future__ import annotations

import hashlib
import re
import uuid

CASE_ID_PATTERN = r"^case_[0-9a-f]{32}$"
RUN_ID_PATTERN = r"^run_[0-9a-f]{32}$"
EXECUTION_ID_PATTERN = r"^exec_[0-9a-f]{32}$"
SESSION_ID_PATTERN = r"^sess_[0-9a-f]{32}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

_CASE_ID = re.compile(CASE_ID_PATTERN)
_SHA256 = re.compile(SHA256_PATTERN)


def new_case_id() -> str:
    return f"case_{uuid.uuid4().hex}"


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def new_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex}"


def new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def sha256_text(text: str) -> str:
    """Hash UTF-8 text. The digest does not contain the input."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_case_id(value: str) -> bool:
    return _CASE_ID.fullmatch(value) is not None


def is_sha256(value: str) -> bool:
    return _SHA256.fullmatch(value) is not None
