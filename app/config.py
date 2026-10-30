from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    egi_checkin_env: str = "dev"
    client_id: str = "client-oidc-dispatcher"
    client_secret: str = "secret-oidc-dispatcher"
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

    # VRE provider healthcheck (fail-fast when a provider is down)
    vre_healthcheck_enabled: bool = True
    vre_healthcheck_timeout: float = 3.0
    # Static VIP API key override for dev instances without vault access.
    # Empty means per-user vault lookup (production behavior).
    vip_api_key: str = ""

    # Async-execution state store (see plans/async-execution-architecture-v3.md)
    db_path: str = "dispatcher.db"
    status_ttl: int = 86400  # seconds; uniform record TTL from creation
    janitor_interval: int = 60  # seconds between recovery manager scans
    stale_task_timeout: int = 3600  # seconds without heartbeat => "worker lost"
    infra_max_lifetime: int | None = None  # TTL-destroy of delivered VMs; OFF
    reap_failure_threshold: int = 5  # reap attempts before escalating to the worklist

    # Shared HTTP client + per-call retry policy
    http_default_timeout: float = 30.0
    http_max_connections: int = 100
    http_max_keepalive_connections: int = 20
    http_retry_attempts: int = 4
    http_retry_min_backoff: float = 1.0  # seconds
    http_retry_max_backoff: float = 30.0  # seconds

    # IM wait bounds (used by the dispatcher-side async IM wrapper)
    im_max_time: int = 36000  # seconds; 10 h
    im_sleep: int = 30  # seconds between IM state polls
    im_max_retries: int = 3  # tolerated consecutive "unknown" IM states
    im_ssl_verify: bool = (
        True  # verify the IM endpoint's TLS cert (disable for dev/self-signed)
    )

    # Bounded poll loops for orchestrated flows
    jupyter_poll_interval: int = 10
    jupyter_wait_max_time: int = 900
    mddash_poll_interval: int = 5
    mddash_wait_max_time: int = 600

    # Logging configuration
    log_level: str = "INFO"
    log_format: str = "text"  # 'text' or 'json' for future expansion


settings = Settings()
