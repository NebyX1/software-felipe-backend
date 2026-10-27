import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Protocol, Iterator
from uuid import uuid4
from flask import current_app


@dataclass(frozen=True)
class StoredObject:
    key: str
    modified_at: float


def validate_key(key: str) -> str:
    if not key or '/' in key or '\\' in key or '..' in key:
        raise ValueError('Invalid storage key')
    return key


class DocumentStoragePort(Protocol):
    kind: str
    def put(self, content: bytes) -> tuple[str, str]: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list_objects(self) -> Iterator[StoredObject]: ...
    def delete(self, key: str) -> None: ...
    def healthy(self) -> bool: ...


class LocalDocumentStorage:
    kind = 'private-volume'

    def __init__(self):
        self.root = Path(current_app.config['DOCUMENT_ROOT']).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        return self.root / validate_key(key)

    def put(self, content):
        key = uuid4().hex
        temp = self.path(key + '.tmp')
        with temp.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.path(key))
        return key, hashlib.sha256(content).hexdigest()

    def read(self, key):
        return self.path(key).read_bytes()

    def exists(self, key):
        return self.path(key).is_file()

    def list_objects(self):
        for path in self.root.iterdir():
            if path.is_file():
                yield StoredObject(path.name, path.stat().st_mtime)

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def healthy(self):
        return self.root.is_dir() and os.access(self.root, os.W_OK)


class MinioDocumentStorage:
    """Private objects; this adapter never creates buckets or changes their policy.

    Keys in the database remain opaque and provider independent. Only objects in
    this project's exclusive prefix may be listed or deleted by reconciliation.
    """
    kind = 'private-minio'
    prefix = 'lavalleja-obras/'

    def __init__(self, client=None):
        from minio import Minio
        import urllib3
        self.bucket = current_app.config['MINIO_BUCKET_NAME']
        if not self.bucket:
            raise ValueError('MINIO_BUCKET_NAME is required')
        self.client = client or Minio(
            current_app.config['MINIO_ENDPOINT'],
            access_key=current_app.config['MINIO_ACCESS_KEY'],
            secret_key=current_app.config['MINIO_SECRET_KEY'],
            secure=current_app.config.get('MINIO_SECURE', True),
            http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=5, read=20), retries=False),
        )

    def _object(self, key):
        return self.prefix + validate_key(key)

    def put(self, content):
        key = uuid4().hex
        digest = hashlib.sha256(content).hexdigest()
        self.client.put_object(self.bucket, self._object(key), BytesIO(content), len(content),
                               content_type='application/octet-stream', metadata={'sha256': digest})
        return key, digest

    def read(self, key):
        response = self.client.get_object(self.bucket, self._object(key))
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key):
        from minio.error import S3Error
        try:
            self.client.stat_object(self.bucket, self._object(key))
            return True
        except S3Error as exc:
            if exc.code in ('NoSuchKey', 'NoSuchObject'):
                return False
            raise

    def list_objects(self):
        for item in self.client.list_objects(self.bucket, prefix=self.prefix, recursive=True):
            key = item.object_name.removeprefix(self.prefix)
            if not item.object_name.startswith(self.prefix) or item.is_dir or '/' in key:
                continue
            validate_key(key)
            modified = item.last_modified
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            yield StoredObject(key, modified.timestamp())

    def delete(self, key):
        self.client.remove_object(self.bucket, self._object(key))

    def healthy(self):
        return self.client.bucket_exists(self.bucket)


def get_document_storage() -> DocumentStoragePort:
    backend = current_app.config.get('DOCUMENT_STORAGE', 'local').lower()
    if backend == 'local':
        return LocalDocumentStorage()
    if backend == 'minio':
        return MinioDocumentStorage()
    raise ValueError('DOCUMENT_STORAGE must be local or minio')
