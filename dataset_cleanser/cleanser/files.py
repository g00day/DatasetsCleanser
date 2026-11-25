import codecs
import hashlib
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db.models import Sum

from .http import APIError
from .models import StoredFile

CSV_MEDIA_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel",
                   "text/plain", "text/comma-separated-values", "application/octet-stream"}
ORPHAN_FILE = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{32}\.tmp)\Z")


class StorageQuotaExceeded(Exception):
    pass


@dataclass
class StagedFile:
    root: Path
    key: str
    size: int = 0
    sha256: str = ""

    @property
    def temporary_path(self):
        return self.root / f"{self.key}.tmp"

    def seal(self, tick=None):
        digest = hashlib.sha256()
        with self.temporary_path.open("rb+") as file:
            while chunk := file.read(64 * 1024):
                digest.update(chunk)
                self.size += len(chunk)
                if tick:
                    tick()
            os.fsync(file.fileno())
        self.sha256 = digest.hexdigest()

    def publish(self, owner_id, kind, name):
        used = StoredFile.objects.filter(owner_id=owner_id).aggregate(
            total=Sum("size_bytes", default=0),
        )["total"]
        if used + self.size > settings.MAX_OWNER_STORAGE_BYTES:
            raise StorageQuotaExceeded
        os.replace(self.temporary_path, self.root / self.key)
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return StoredFile.objects.create(owner_id=owner_id, storage_key=self.key, original_name=name,
                                         media_type="text/csv", size_bytes=self.size, sha256=self.sha256, kind=kind)


@contextmanager
def stage_file():
    root = settings.PRIVATE_FILE_ROOT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    staged = StagedFile(root, uuid4().hex)
    staged.temporary_path.touch(mode=0o600, exist_ok=False)
    try:
        yield staged
    finally:
        staged.temporary_path.unlink(missing_ok=True)


def safe_file_name(name):
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join("_" if ord(char) < 32 or ord(char) == 127 else char for char in leaf).strip()
    if len(cleaned) > 255:
        cleaned = cleaned[:251] + ".csv"
    return cleaned


def download_name(version_name):
    return safe_file_name(f"{version_name.replace('/', '_').replace(chr(92), '_')}.csv")


def stage_upload(upload, staged):
    name = safe_file_name(upload.name)
    media_type = (upload.content_type or "application/octet-stream").lower()
    if not name.lower().endswith(".csv") or media_type not in CSV_MEDIA_TYPES:
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "Поддерживаются только файлы CSV.")
    if upload.size > settings.MAX_FILE_BYTES:
        raise APIError(413)
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    try:
        with staged.temporary_path.open("wb") as file:
            for chunk in upload.chunks():
                staged.size += len(chunk)
                if staged.size > settings.MAX_FILE_BYTES:
                    raise APIError(413)
                if "\x00" in decoder.decode(chunk):
                    raise UnicodeError
                digest.update(chunk)
                file.write(chunk)
            decoder.decode(b"", final=True)
            file.flush()
            os.fsync(file.fileno())
    except UnicodeError:
        raise APIError(415, "UNSUPPORTED_ENCODING", "Поддерживается только текст UTF-8.") from None
    staged.sha256 = digest.hexdigest()
    return name


def stored_path(file):
    return settings.PRIVATE_FILE_ROOT / file.storage_key


def remove_orphan_files():
    root = settings.PRIVATE_FILE_ROOT
    if not root.exists():
        return
    # A crash between filesystem publication and SQL commit leaves an unreferenced artifact.
    cutoff = time.time() - max(86_400, settings.JOB_TIMEOUT_SECONDS * 2)
    for path in root.iterdir():
        if not ORPHAN_FILE.fullmatch(path.name):
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            if path.suffix == ".tmp" or not StoredFile.objects.filter(storage_key=path.name).exists():
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
