from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    egi_checkin_env: str = "dev"
    client_id: str = "client-oidc-dispatcher"
    client_secret: str = "secret-oidc-dispatcher"
    # HS256 signing key for fastapi-oauth2 session tokens. Must be set by the
    # deployment (ansible vault / local host_vars): python-jose verifies
    # HS256 with an empty key, so the default "" would let anyone forge
    # session tokens.
    jwt_secret: str = ""
    redirect_uri: str = ""
    cert_chain_file: str = ""
    private_key_file: str = ""
    host: str = ""
    git_repos: str = ""
    git_url_prefix: str = "/git"
    # Anonymous (unauthenticated) request endpoints /anon_requests/
    anonymous_requests_enabled: bool = True
    im_endpoint: str = ""
    im_cloud_provider: dict = {}

    # Vault (EGI Secret Store) configuration
    vault_url: str = ""
    vault_jwt_mount: str = "jwt"
    vault_kv_mount: str = "secrets"
    vault_kv_version: int = 1
    vault_jwt_role: str = ""

    # Static VIP API key override for dev instances without vault access.
    # Empty means per-user vault lookup (production behavior).
    vip_api_key: str = ""

    # Logging configuration
    log_level: str = "INFO"
    log_format: str = "text"  # 'text' or 'json' for future expansion


settings = Settings()


def get_jwt_secret() -> str:
    """Resolve the HS256 session-token key, fail-closed.

    An empty secret is not "no secret": python-jose verifies HS256 with an
    empty key, so "" would let anyone forge a session token. The value is
    always provided by the deployment (ansible vault for dispatchers,
    host_vars for local development).
    """
    if settings.jwt_secret:
        return settings.jwt_secret
    raise RuntimeError(
        "settings.jwt_secret must be set by the deployment: it is the HS256 "
        "key for fastapi-oauth2 session tokens and must not be empty"
    )
