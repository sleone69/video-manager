"""Google Drive image adapter (service account).

Uploads a thumbnail to a specified Google Drive folder, makes it
publicly readable, and returns the direct image URL.

Requires:
  GDRIVE_SERVICE_ACCOUNT_JSON = /path/to/service-account.json
  GDRIVE_FOLDER_ID            = <Drive folder id>  (optional)
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Dict, Optional

from .base import ImageHostAdapter
from ..config import settings

# google-api-python-client is a sync library; we run it in a thread executor.
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GDriveAdapter(ImageHostAdapter):
    name = "gdrive"

    def __init__(self) -> None:
        self._sa_json: Optional[Path] = settings.gdrive_service_account_json
        self._folder_id: Optional[str] = settings.gdrive_folder_id

    def _build_service(self):
        if not _GDRIVE_AVAILABLE:
            raise RuntimeError(
                "google-api-python-client not installed. "
                "Run: pip install google-api-python-client google-auth"
            )
        if not self._sa_json or not Path(self._sa_json).exists():
            raise RuntimeError(
                "GDRIVE_SERVICE_ACCOUNT_JSON is not set or file does not exist."
            )
        creds = service_account.Credentials.from_service_account_file(
            str(self._sa_json), scopes=_SCOPES
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _upload_sync(self, path: Path) -> Dict[str, str]:
        service = self._build_service()

        file_metadata: dict = {"name": path.name}
        if self._folder_id:
            file_metadata["parents"] = [self._folder_id]

        media = MediaFileUpload(str(path), resumable=False)
        file_obj = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id,webContentLink")
            .execute()
        )

        file_id = file_obj["id"]

        # Make public
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        # Build a direct embed/thumbnail URL
        direct_url = f"https://drive.google.com/uc?export=view&id={file_id}"
        return {"url": direct_url, "file_id": file_id}

    async def upload(self, path: Path) -> Dict[str, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._upload_sync, path)
