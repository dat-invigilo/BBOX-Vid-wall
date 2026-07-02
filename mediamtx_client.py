"""
Thin REST client for mediamtx's HTTP control API (v3).
Used to provision RTSP relay paths dynamically instead of hand-editing mediamtx.yml.
"""
import logging
import requests

logger = logging.getLogger(__name__)


class MediamtxClient:
    """Client for mediamtx's /v3/config/paths API"""

    def __init__(self, base_url: str = "http://127.0.0.1:9997", timeout: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def upsert_path(self, name: str, config: dict):
        """Create the path if it doesn't exist yet, otherwise patch it in place"""
        r = requests.post(
            f"{self.base_url}/v3/config/paths/add/{name}",
            json=config, timeout=self.timeout
        )
        if r.status_code == 400:
            r = requests.post(
                f"{self.base_url}/v3/config/paths/patch/{name}",
                json=config, timeout=self.timeout
            )
        r.raise_for_status()

    def delete_path(self, name: str):
        """Best-effort path removal; failures are logged, not raised"""
        try:
            r = requests.post(
                f"{self.base_url}/v3/config/paths/delete/{name}",
                timeout=self.timeout
            )
            if r.status_code not in (200, 404):
                r.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"mediamtx: failed to delete path '{name}': {e}")

    def list_paths(self) -> dict:
        r = requests.get(f"{self.base_url}/v3/paths/list", timeout=self.timeout)
        r.raise_for_status()
        return r.json()
