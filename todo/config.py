"""Lakebase connection settings + live OAuth-token resolution via the Databricks SDK.

No host/user/token is ever read from files. Only branch *identity* comes from the
environment (`LAKEBASE_*`); the host is discovered and the password (a Databricks OAuth
token) is minted live via the SDK and cached just under its 1-hour lifetime.
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into the process environment so the Databricks SDK (WorkspaceClient) picks up
# DATABRICKS_CONFIG_PROFILE and friends — pydantic reads .env for LAKEBASE_* but does not
# export to os.environ, which is where the SDK looks.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAKEBASE_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    project_id: str = "todo-branching-demo"
    branch_id: str = "production"
    endpoint_id: str = "primary"
    database: str = "databricks_postgres"
    # Env var LAKEBASE_SCHEMA (alias bypasses the env_prefix in pydantic-settings v2).
    schema_name: str = Field(default="todo_app", alias="LAKEBASE_SCHEMA")

    def endpoint_path(self) -> str:
        return (
            f"projects/{self.project_id}/branches/{self.branch_id}"
            f"/endpoints/{self.endpoint_id}"
        )

    # --- live resolution via the Databricks SDK ---
    def get_host(self) -> str:
        ep = _workspace_client().postgres.get_endpoint(name=self.endpoint_path())
        return ep.status.hosts.host

    def get_user(self) -> str:
        w = _workspace_client()
        return w.config.client_id or w.current_user.me().user_name

    def get_password(self) -> str:
        return _token_manager.get(self.endpoint_path())

    def database_url(self) -> str:
        user = quote_plus(self.get_user())
        token = quote_plus(self.get_password())
        host = self.get_host()
        return (
            f"postgresql+psycopg://{user}:{token}@{host}:5432/{self.database}"
            f"?sslmode=require&connect_timeout=30"
            f"&options=-csearch_path%3D{self.schema_name}"
        )


@lru_cache(maxsize=1)
def _workspace_client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


class _OAuthTokenManager:
    """Caches the per-endpoint OAuth token, refreshing ~10 min before expiry."""

    def __init__(self, ttl_seconds: int = 3000):  # 50 min
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str, float]] = {}

    def get(self, endpoint_path: str) -> str:
        with self._lock:
            token, expiry = self._cache.get(endpoint_path, (None, 0.0))
            if token and time.time() < expiry:
                return token
            cred = _workspace_client().postgres.generate_database_credential(
                endpoint_path
            )
            self._cache[endpoint_path] = (cred.token, time.time() + self._ttl)
            return cred.token


_token_manager = _OAuthTokenManager()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
