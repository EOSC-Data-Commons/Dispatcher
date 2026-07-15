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
    im_endpoint: str = ""
    im_cloud_provider: dict = {}

    # Rancher / Kubernetes deployment mode
    # "local" – use a static kubeconfig file (/usr/src/app/k8s-config.yaml)
    # "dev"   – exchange the user's EGI token for a Rancher token,
    #           generate a kubeconfig from the Rancher API, and use it.
    rancher_mode: str = "local"

    # Dev Rancher settings (only used when rancher_mode = "dev")
    rancher_dev_url: str = ""
    rancher_dev_token_exchange_url: str = ""
    rancher_dev_client_id: str = ""
    rancher_dev_client_secret: str = ""
    rancher_dev_audience: str = ""

    # Logging configuration
    log_level: str = "INFO"
    log_format: str = "text"  # 'text' or 'json' for future expansion


settings = Settings()
