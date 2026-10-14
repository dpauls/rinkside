"""Decoupled Storage Backend for local testing and cloud object storage (S3 / R2)."""
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract storage interface for tournament state."""

    @abstractmethod
    def save_state(self, state: Dict[str, Any], filename: str = "state.json") -> bool:
        """Persist state data."""
        pass

    @abstractmethod
    def save_streams(self, streams: Dict[str, Any], filename: str = "streams.json") -> bool:
        """Persist streams dictionary."""
        pass

    @abstractmethod
    def load_streams(self, filename: str = "streams.json") -> Optional[Dict[str, Any]]:
        """Retrieve streams dictionary."""
        pass

    @abstractmethod
    def get_public_url(self, filename: str = "state.json") -> Optional[str]:
        """Return public URL for client consumption if available."""
        pass


class LocalStorage(StorageBackend):
    """Local filesystem storage (e.g. docs/data/state.json)."""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            self.base_dir = Path(__file__).parent.parent / "docs" / "data"
        else:
            self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(__file__).parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: Dict[str, Any], filename: str = "state.json") -> bool:
        try:
            target = self.base_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(state, indent=2)
            target.write_text(content)
            return True
        except Exception as e:
            log.error(f"LocalStorage save error: {e}")
            return False

    def load_state(self, filename: str = "state.json") -> Optional[Dict[str, Any]]:
        target = self.base_dir / filename
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text())
        except Exception as e:
            log.error(f"LocalStorage load error: {e}")
            return None

    def save_streams(self, streams: Dict[str, Any], filename: str = "streams.json") -> bool:
        try:
            target = self.data_dir / filename
            target.write_text(json.dumps(streams, indent=2))
            return True
        except Exception as e:
            log.error(f"LocalStorage save_streams error: {e}")
            return False

    def load_streams(self, filename: str = "streams.json") -> Optional[Dict[str, Any]]:
        target = self.data_dir / filename
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text())
        except Exception as e:
            log.error(f"LocalStorage load_streams error: {e}")
            return None

    def get_public_url(self, filename: str = "state.json") -> Optional[str]:
        return f"data/{filename}"


class S3Storage(StorageBackend):
    """AWS S3, Cloudflare R2, or OCI Object Storage with local mirror."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        prefix: str = "data",
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
        local_mirror_dir: Optional[Path] = None
    ):
        self.bucket = bucket_name or os.environ.get("S3_BUCKET_NAME")
        self.prefix = prefix
        self.endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT_URL")
        self.region_name = region_name or os.environ.get("AWS_DEFAULT_REGION", "ca-toronto-1")
        self.local_storage = LocalStorage(local_mirror_dir)
        self._s3_client = None

        if self.bucket:
            try:
                import boto3
                self._s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    region_name=self.region_name
                )
            except ImportError:
                log.warning("S3Storage: boto3 package not installed. Operating in local-mirror mode only.")

    def save_state(self, state: Dict[str, Any], filename: str = "state.json") -> bool:
        # Dual-write locally first
        self.local_storage.save_state(state, filename)

        if not self._s3_client or not self.bucket:
            log.warning("S3Storage: S3 client or bucket not configured. Saved to local mirror only.")
            return True

        key = f"{self.prefix}/{filename}".lstrip("/")
        try:
            payload = json.dumps(state, indent=2).encode("utf-8")
            self._s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType="application/json",
                CacheControl="no-cache, no-store, must-revalidate"
            )
            log.info(f"S3Storage: Successfully uploaded s3://{self.bucket}/{key}")
            return True
        except Exception as e:
            log.error(f"S3Storage upload error for key {key}: {e}")
            return False

    def load_state(self, filename: str = "state.json") -> Optional[Dict[str, Any]]:
        if not self._s3_client or not self.bucket:
            return self.local_storage.load_state(filename)

        key = f"{self.prefix}/{filename}".lstrip("/")
        try:
            resp = self._s3_client.get_object(Bucket=self.bucket, Key=key)
            data = resp["Body"].read().decode("utf-8")
            return json.loads(data)
        except Exception as e:
            log.warning(f"S3Storage get error for key {key}: {e}. Trying local mirror.")
            return self.local_storage.load_state(filename)

    def save_streams(self, streams: Dict[str, Any], filename: str = "streams.json") -> bool:
        self.local_storage.save_streams(streams, filename)
        if not self._s3_client or not self.bucket:
            return True

        key = f"{self.prefix}/{filename}".lstrip("/")
        try:
            payload = json.dumps(streams, indent=2).encode("utf-8")
            self._s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType="application/json",
                CacheControl="no-cache, no-store, must-revalidate"
            )
            log.info(f"S3Storage: Successfully uploaded streams s3://{self.bucket}/{key}")
            return True
        except Exception as e:
            log.error(f"S3Storage streams upload error for key {key}: {e}")
            return False

    def load_streams(self, filename: str = "streams.json") -> Optional[Dict[str, Any]]:
        if not self._s3_client or not self.bucket:
            return self.local_storage.load_streams(filename)

        key = f"{self.prefix}/{filename}".lstrip("/")
        try:
            resp = self._s3_client.get_object(Bucket=self.bucket, Key=key)
            data = resp["Body"].read().decode("utf-8")
            return json.loads(data)
        except Exception as e:
            return self.local_storage.load_streams(filename)

    def get_public_url(self, filename: str = "state.json") -> Optional[str]:
        if os.environ.get("S3_PUBLIC_URL"):
            base = os.environ.get("S3_PUBLIC_URL").rstrip("/")
            return f"{base}/{filename}" if not base.endswith(filename) else base

        if not self.bucket:
            return f"data/{filename}"

        key = f"{self.prefix}/{filename}".lstrip("/")
        # OCI compatibility endpoint detection
        if self.endpoint_url and "compat.objectstorage" in self.endpoint_url:
            import re
            m = re.search(r"https?://([^.]+)\.compat\.objectstorage\.([^.]+)\.oraclecloud\.com", self.endpoint_url)
            if m:
                namespace, region = m.group(1), m.group(2)
                return f"https://objectstorage.{region}.oraclecloud.com/n/{namespace}/b/{self.bucket}/o/{key}"

        return f"https://{self.bucket}.s3.{self.region_name}.amazonaws.com/{key}"


def build_storage(storage_type: str = "local", **kwargs: Any) -> StorageBackend:
    """Factory helper to build StorageBackend."""
    if storage_type.lower() == "s3":
        return S3Storage(**kwargs)
    return LocalStorage(**kwargs)
