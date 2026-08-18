"""Authenticated HTTP client for the internal inference runtime."""

import httpx


class InferenceRuntimeClientError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class InferenceRuntimeClient:
    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        load_timeout_seconds: float = 60,
        predict_timeout_seconds: float = 30,
        client=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Inference-Internal-Token": internal_token}
        self.load_timeout_seconds = load_timeout_seconds
        self.predict_timeout_seconds = predict_timeout_seconds
        self.client = client or httpx

    @staticmethod
    def _code(response, fallback: str) -> str:
        try:
            code = response.json().get("detail", {}).get("code")
        except Exception:
            code = None
        return str(code or fallback)

    def _request(self, method, path, *, timeout, json=None):
        try:
            response = self.client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                json=json,
                timeout=timeout,
            )
        except Exception:
            raise InferenceRuntimeClientError(
                "INFERENCE_RUNTIME_UNAVAILABLE"
            ) from None
        if not 200 <= int(response.status_code) < 300:
            raise InferenceRuntimeClientError(
                self._code(response, "INFERENCE_RUNTIME_UNAVAILABLE")
            )
        return response.json()

    def load(self, runtime_key, specification):
        return self._request(
            "PUT",
            f"/internal/deployments/{runtime_key}",
            json=specification,
            timeout=self.load_timeout_seconds,
        )

    def unload(self, runtime_key):
        return self._request(
            "DELETE",
            f"/internal/deployments/{runtime_key}",
            timeout=self.load_timeout_seconds,
        )

    def predict(self, runtime_key, records):
        return self._request(
            "POST",
            f"/internal/deployments/{runtime_key}/predict",
            json={"records": records},
            timeout=self.predict_timeout_seconds,
        )

    def list(self):
        return self._request(
            "GET",
            "/internal/deployments",
            timeout=self.load_timeout_seconds,
        )
