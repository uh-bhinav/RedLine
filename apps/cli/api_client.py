"""
Thin httpx client wrapping the RedLine API.
All CLI commands use this -- never calling the DB or any other service directly.
"""
from __future__ import annotations

import httpx


class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class RedLineClient:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for(self, response: httpx.Response) -> httpx.Response:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, str(detail))
        return response

    def get(self, path: str) -> dict:
        r = httpx.get(f"{self._base_url}{path}", headers=self._headers, timeout=30)
        return self._raise_for(r).json()

    def post(self, path: str, payload: dict) -> dict:
        r = httpx.post(f"{self._base_url}{path}", headers=self._headers, json=payload, timeout=30)
        return self._raise_for(r).json()