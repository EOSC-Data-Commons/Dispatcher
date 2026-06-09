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

    # Logging configuration
    log_level: str = "INFO"
    log_format: str = "text"  # 'text' or 'json' for future expansion


settings = Settings()
