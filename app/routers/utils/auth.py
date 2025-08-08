from fastapi_oauth2.security import OAuth2AuthorizationCodeBearer

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="/oauth2/login", tokenUrl="/oauth2/egi-checkin/token"
)
