import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    api_origin: str = os.getenv("ANNOTATOR_API_ORIGIN", "http://localhost:8000")
    public_origin: str = os.getenv("ANNOTATOR_PUBLIC_ORIGIN", "http://localhost:8443")
    port: int = int(os.getenv("ANNOTATOR_PORT", "8443"))
    service_issuer: str = os.getenv("ANNOTATOR_SERVICE_ISSUER", "ml-platform-annotator")
    service_audience: str = os.getenv("ANNOTATOR_SERVICE_AUDIENCE", "ml-platform-internal")
    service_secret: str = os.getenv("ANNOTATOR_SERVICE_SECRET", "change-me-annotator-service-secret")
    # 纯 HTTP 部署（如内网 IP 直访）必须设为 false：浏览器会丢弃经非安全
    # 传输下发的 Secure cookie，导致登录成功但会话立即丢失。
    cookie_secure: bool = os.getenv("ANNOTATOR_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}

settings = Settings()
