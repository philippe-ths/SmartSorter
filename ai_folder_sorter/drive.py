from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from glob import glob

from google.auth.exceptions import RefreshError


@dataclass(frozen=True)
class GooglePreviewStatus:
    is_google: bool
    google_fetched: bool
    is_essentially_empty: bool
    file_id: Optional[str] = None
    error: Optional[str] = None


def _google_creds() -> Optional[object]:
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]

    client_file_env = os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    client_file: Optional[str] = client_file_env or None

    if not client_file:
        # Convenience fallback for local development: if a client secret file is present in the repo root,
        # use it without requiring env vars.
        repo_root = Path(__file__).resolve().parents[1]
        candidates = sorted(glob(str(repo_root / "client_secret_*.json")))
        if candidates:
            client_file = candidates[0]

    if client_file:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials as _UserCreds
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_path = Path(client_file).expanduser().resolve()
        token_file_env = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "").strip()
        token_path = Path(token_file_env).expanduser().resolve() if token_file_env else client_path.with_name("token.json")
        # Secondary fallback for local dev: a repo-root token.json (common in this workspace).
        if not token_path.exists():
            repo_token = Path(__file__).resolve().parents[1] / "token.json"
            if repo_token.exists():
                token_path = repo_token.resolve()

        creds: Optional[_UserCreds] = None
        if token_path.exists():
            creds = _UserCreds.from_authorized_user_file(str(token_path), scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    # Token is invalid/revoked. Only attempt interactive auth if explicitly enabled.
                    if os.environ.get("GOOGLE_OAUTH_INTERACTIVE", "").strip().lower() in {"1", "true", "yes", "y"}:
                        creds = None
                    else:
                        return None
            if not creds or not creds.valid:
                if os.environ.get("GOOGLE_OAUTH_INTERACTIVE", "").strip().lower() in {"1", "true", "yes", "y"}:
                    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
                    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
                    token_path.write_text(creds.to_json(), encoding="utf-8")
                else:
                    return None

        return creds

    try:
        import google.auth

        creds, _ = google.auth.default(scopes=scopes)
        return creds
    except Exception:
        return None


def _drive_service(creds: object):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def export_google_stub_text(file_id: str, *, is_sheet: bool, max_chars: int, creds: object) -> str:
    service = _drive_service(creds)
    mime = "text/csv" if is_sheet else "text/plain"
    data = service.files().export(fileId=file_id, mimeType=mime).execute()
    text = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    if isinstance(max_chars, int) and max_chars > 0:
        return text[:max_chars]
    return text


def google_stub_header(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        obj = json.loads(raw or "{}")
    except Exception:
        return f"[google-stub] {path.name}\n"

    title = obj.get("title") or obj.get("name") or path.stem
    url = obj.get("url") or obj.get("open_url") or obj.get("alternateLink") or obj.get("alternate_link")
    mime = obj.get("mimeType") or obj.get("mime_type")
    bits = [f"[google-stub] {title}"]
    if mime:
        bits.append(f"mime={mime}")
    if url:
        bits.append(f"url={url}")
    return " ".join(bits).strip() + "\n"


def google_preview_for_stub(
    path: Path,
    *,
    file_id: Optional[str],
    max_chars: int,
) -> tuple[str, GooglePreviewStatus]:
    header = google_stub_header(path)
    if not file_id:
        return (
            header,
            GooglePreviewStatus(is_google=True, google_fetched=False, is_essentially_empty=True, error="no file id"),
        )

    try:
        creds = _google_creds()
    except Exception as e:
        return (
            header,
            GooglePreviewStatus(
                is_google=True,
                google_fetched=False,
                is_essentially_empty=True,
                file_id=file_id,
                error=f"google creds error: {e}",
            ),
        )
    if not creds:
        return (
            header,
            GooglePreviewStatus(
                is_google=True,
                google_fetched=False,
                is_essentially_empty=True,
                file_id=file_id,
                error="no google credentials (set GOOGLE_OAUTH_CLIENT_FILE or enable GOOGLE_OAUTH_INTERACTIVE=1)",
            ),
        )

    ext = path.suffix.lower()
    if ext == ".gform":
        return (
            header,
            GooglePreviewStatus(is_google=True, google_fetched=False, is_essentially_empty=True, file_id=file_id),
        )

    is_sheet = ext == ".gsheet"
    try:
        body = export_google_stub_text(file_id, is_sheet=is_sheet, max_chars=max_chars, creds=creds)
        combined = (header + "\n" + body).strip()
        essentially_empty = len(body.strip()) == 0
        return (
            combined,
            GooglePreviewStatus(
                is_google=True,
                google_fetched=True,
                is_essentially_empty=essentially_empty,
                file_id=file_id,
            ),
        )
    except Exception as e:
        return (
            header,
            GooglePreviewStatus(
                is_google=True,
                google_fetched=False,
                is_essentially_empty=True,
                file_id=file_id,
                error=str(e),
            ),
        )
