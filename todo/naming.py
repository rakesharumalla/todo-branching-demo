"""Deterministic mapping from git branch -> Lakebase branch name + local port.

Kept dependency-free so the git hook can call it via `python -c`.
"""
import hashlib
import re

_MAIN_BRANCHES = {"main", "master", "production"}


def _slug(s: str) -> str:
    """Lowercase and collapse to an RFC-1123-safe token ([a-z0-9-])."""
    s = s.lower().replace(".", "-").replace("/", "-").replace("_", "-")
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def lakebase_branch_name(user_prefix: str, git_branch: str) -> str:
    """`{user}-{git_branch}` sanitized to a valid Lakebase branch id (<=63 chars)."""
    name = f"{_slug(user_prefix)}-{_slug(git_branch)}"
    return name[:63].strip("-")


def port_for_branch(git_branch: str, base: int = 8501) -> int:
    """Base port for main/production; a deterministic 8502-8599 port otherwise."""
    if git_branch in _MAIN_BRANCHES:
        return base
    h = int(hashlib.sha1(git_branch.encode()).hexdigest(), 16)
    return 8502 + (h % 98)  # 8502..8599
