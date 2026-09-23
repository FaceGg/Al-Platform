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

settings = Settings()
