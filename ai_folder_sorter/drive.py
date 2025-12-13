from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple

from .models import DriveItem


READ_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def google_creds(scopes: list[str]) -> object:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials as UserCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_file = os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    if client_file:
        client_path = Path(client_file).expanduser().resolve()
        token_file_env = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "").strip()
        token_path = Path(token_file_env).expanduser().resolve() if token_file_env else client_path.with_name("token.json")

        creds: Optional[UserCredentials] = None
        if token_path.exists():
            creds = UserCredentials.from_authorized_user_file(str(token_path), scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
                creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    import google.auth

    creds, _ = google.auth.default(scopes=scopes)
    return creds


def drive_service(scopes: list[str]) -> Any:
    from googleapiclient.discovery import build

    creds = google_creds(scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_top_level_children(folder_id: str, *, supports_all_drives: bool) -> list[DriveItem]:
    service = drive_service(scopes=READ_SCOPES)

    q = f"'{folder_id}' in parents and trashed=false"
    items: list[DriveItem] = []
    page_token: Optional[str] = None

    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                pageToken=page_token,
                pageSize=1000,
                supportsAllDrives=supports_all_drives,
                includeItemsFromAllDrives=supports_all_drives,
            )
            .execute()
        )
        for f in resp.get("files", []) or []:
            items.append(
                DriveItem(
                    id=f["id"],
                    name=f.get("name") or "",
                    mime_type=f.get("mimeType") or "",
                    modified_time=f.get("modifiedTime"),
                )
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return items


def export_google_native_text(file_id: str, *, mime_type: str, max_chars: int, supports_all_drives: bool) -> Optional[str]:
    service = drive_service(scopes=READ_SCOPES)

    if mime_type == "application/vnd.google-apps.spreadsheet":
        export_mime = "text/csv"
    elif mime_type in {
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.drawing",
    }:
        export_mime = "text/plain"
    else:
        return None

    data = (
        service.files()
        .export(fileId=file_id, mimeType=export_mime, supportsAllDrives=supports_all_drives)
        .execute()
    )
    text = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    return text[:max_chars] if max_chars and max_chars > 0 else text


def download_text_like_file(file_id: str, *, mime_type: str, max_chars: int, supports_all_drives: bool) -> Optional[str]:
    if not (mime_type.startswith("text/") or mime_type in {"application/json", "application/xml"}):
        return None

    service = drive_service(scopes=READ_SCOPES)
    data = service.files().get_media(fileId=file_id, supportsAllDrives=supports_all_drives).execute()
    text = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    return text[:max_chars] if max_chars and max_chars > 0 else text


def find_child_by_name(parent_folder_id: str, *, name: str, supports_all_drives: bool) -> Optional[DriveItem]:
    service = drive_service(scopes=READ_SCOPES)
    safe_name = (name or "").replace("'", "\\'")
    q = f"'{parent_folder_id}' in parents and trashed=false and name='{safe_name}'"
    resp = (
        service.files()
        .list(
            q=q,
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=10,
            supportsAllDrives=supports_all_drives,
            includeItemsFromAllDrives=supports_all_drives,
        )
        .execute()
    )
    files = resp.get("files", []) or []
    if not files:
        return None
    f = files[0]
    return DriveItem(
        id=f["id"],
        name=f.get("name") or "",
        mime_type=f.get("mimeType") or "",
        modified_time=f.get("modifiedTime"),
    )


def read_small_text_file(file_id: str, *, max_chars: int, supports_all_drives: bool) -> Optional[str]:
    service = drive_service(scopes=READ_SCOPES)
    data = service.files().get_media(fileId=file_id, supportsAllDrives=supports_all_drives).execute()
    text = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    return text[:max_chars] if max_chars and max_chars > 0 else text


def ensure_folder(parent_folder_id: str, *, name: str, supports_all_drives: bool) -> str:
    existing = find_child_by_name(parent_folder_id, name=name, supports_all_drives=supports_all_drives)
    if existing and existing.is_folder:
        return existing.id

    service = drive_service(scopes=READ_SCOPES + WRITE_SCOPES)
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_folder_id]}
    created = service.files().create(body=meta, fields="id", supportsAllDrives=supports_all_drives).execute()
    return created["id"]


def move_file(file_id: str, *, from_parent_id: str, to_parent_id: str, supports_all_drives: bool) -> None:
    service = drive_service(scopes=READ_SCOPES + WRITE_SCOPES)
    service.files().update(
        fileId=file_id,
        addParents=to_parent_id,
        removeParents=from_parent_id,
        fields="id, parents",
        supportsAllDrives=supports_all_drives,
    ).execute()


def upsert_index_md(
    folder_id: str,
    *,
    index_markdown: str,
    supports_all_drives: bool,
) -> Tuple[str, bool]:
    existing = find_child_by_name(folder_id, name="_index.md", supports_all_drives=supports_all_drives)
    service = drive_service(scopes=READ_SCOPES + WRITE_SCOPES)

    from googleapiclient.http import MediaInMemoryUpload

    media = MediaInMemoryUpload(index_markdown.encode("utf-8"), mimetype="text/markdown", resumable=False)
    if existing:
        updated = (
            service.files()
            .update(
                fileId=existing.id,
                media_body=media,
                fields="id",
                supportsAllDrives=supports_all_drives,
            )
            .execute()
        )
        return updated["id"], False

    meta = {"name": "_index.md", "parents": [folder_id], "mimeType": "text/markdown"}
    created = (
        service.files()
        .create(body=meta, media_body=media, fields="id", supportsAllDrives=supports_all_drives)
        .execute()
    )
    return created["id"], True
