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
    im_endpoint: str = ""
    im_cloud_provider: dict = {}
    im_max_time: int = 36000 # 10h
    im_sleep: int = 30
    im_max_retries: int = 3
    redis_port: int = 6379

settings = Settings()
