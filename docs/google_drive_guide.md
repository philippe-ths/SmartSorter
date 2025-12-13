# Google Drive Integration: Fetching Previews for Summaries

This document explains (in reproducible technical detail) how to fetches Google Drive **file contents / previews** for Google Docs/Sheets/Slides link stubs (e.g. `.gdoc`, `.gsheet`, `.gslides`, `.gform`).

Scope:

- Only the Google Drive integration: **auth**, **ID extraction**, **Drive API export**, **fallback behavior**, and **common issues**.

## What problem we solve

When you use Google Drive for Desktop (or similar sync clients), Google-native files often appear locally as small “link stub” files:

- `.gdoc` (Google Docs)
- `.gsheet` (Google Sheets)
- `.gslides` (Google Slides)
- `.gform` (Google Forms)

These local stubs usually contain only metadata (title, URL), not the real document body.

To summarize the file meaningfully, we “dereference” the stub using the Google Drive API:

- Extract the **Drive file ID** from the stub
- Obtain Google credentials
- Call `drive.files().export(fileId=..., mimeType=...)` and decode the bytes into text

## Dependencies

Needed packages:

- `google-api-python-client`
- `google-auth-oauthlib`

`google-auth` is pulled in as a dependency.

## Authentication (how credentials are obtained)

It uses this preference order:

1) **Installed-app OAuth (browser flow)** if `GOOGLE_OAUTH_CLIENT_FILE` is configured
2) **ADC (Application Default Credentials)** fallback via `google.auth.default()`

### Option A: Installed-app OAuth (recommended for local runs)

#### Google Cloud setup (one-time)

1) In Google Cloud Console, create or select a project.
2) Enable **Google Drive API** for the project.
3) Configure the **OAuth consent screen** (required to issue OAuth tokens).
4) Create OAuth credentials: **OAuth client ID** → **Desktop app**.
5) Download the client secret JSON file (this is what `GOOGLE_OAUTH_CLIENT_FILE` points to).

Configuration is environment-variable driven:

- `GOOGLE_OAUTH_CLIENT_FILE`: path to your OAuth client secret JSON downloaded from Google Cloud Console
- `GOOGLE_OAUTH_TOKEN_FILE` (optional): where to cache the user token; defaults to `token.json` next to the client secret file

The code (as implemented):

```py
def _google_creds() -> Optional[object]:
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials as _UserCreds
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_file = os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    client_path = Path(client_file).expanduser().resolve()

    token_file_env = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "").strip()
    token_path = (
        Path(token_file_env).expanduser().resolve() if token_file_env else client_path.with_name("token.json")
    )

    creds: Optional[_UserCreds] = None
    if token_path.exists():
        creds = _UserCreds.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
            # Key settings:
            # - access_type="offline" ensures a refresh token is granted
            # - prompt="consent" forces re-consent if needed to re-issue refresh token
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds
```

Notes:

- The browser flow will open a local callback server on `localhost`.
- Tokens are cached and refreshed automatically.
- Scope is `drive.readonly`.

### Option B: ADC (Application Default Credentials)

If `GOOGLE_OAUTH_CLIENT_FILE` is not set (or installed-app flow fails), `_google_creds()` falls back to:

```py
import google.auth
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
```

This supports:

- `gcloud auth application-default login` on developer machines
- service-account credentials (common in CI)

## How we detect Google link stubs and extract the file ID

The integration assumes `.gdoc/.gsheet/.gslides/.gform` are local stub files containing JSON.

### ID extraction strategy

`ai_folder_sorter/utils.py::extract_google_id_from_stub(path)` tries, in order:

1) parse JSON and read known fields: `id`, `doc_id`, `resource_id`
2) parse URL fields and extract `/d/<ID>`
3) fallback: regex scan any `/d/<ID>` in the raw content

Code excerpt (as implemented):

```py
_GOOGLE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")

def extract_google_id_from_stub(path: Path) -> Optional[str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        obj = json.loads(raw or "{}")
    except Exception:
        raw, obj = None, {}

    for k in ("id", "doc_id", "resource_id"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    for k in ("url", "open_url", "alternate_link", "alternateLink", "app_url"):
        v = obj.get(k)
        if isinstance(v, str) and v:
            m = _GOOGLE_ID_RE.search(v)
            if m:
                return m.group(1)

    if raw:
        m = _GOOGLE_ID_RE.search(raw)
        if m:
            return m.group(1)

    return None
```

Important limitation:

- This regex targets URL shapes containing `/d/<id>`.
- Some Drive URLs use `?id=<id>` (especially older sharing URLs). If you see “no ID found”, extend `_GOOGLE_ID_RE` to also match `id=`.

## How we fetch the document body (Drive API export)

The content fetch happens through **Drive v3** using the export endpoint:

### Drive service construction

```py
from googleapiclient.discovery import build

service = build("drive", "v3", credentials=creds, cache_discovery=False)
```

### Export call

`ai_folder_sorter/utils.py::_export_google_text(file_id, is_sheet, max_chars, creds)` implements the export:

```py
def _export_google_text(file_id: str, is_sheet: bool, max_chars: Optional[int], creds: object) -> Optional[str]:
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    mime = "text/csv" if is_sheet else "text/plain"
    data = service.files().export(fileId=file_id, mimeType=mime).execute()
    text = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
    return text[:max_chars] if isinstance(max_chars, int) and max_chars > 0 else text
```

Current mapping:

- `.gdoc` → `text/plain`
- `.gsheet` → `text/csv`
- `.gslides` → currently treated as “doc-like” and exported as `text/plain` (this often fails; see “Common issues”)
- `.gform` → export is intentionally not attempted (Forms export isn’t supported by this code path)

### Metadata call (debugging/caching signal)

We also fetch minimal metadata (currently used for debugging and potential caching decisions):

```py
meta = service.files().get(fileId=file_id, fields="modifiedTime,mimeType").execute()
```

## Putting it together: preview text + status

The helper that produces the final preview and status flags is:

- `ai_folder_sorter/utils.py::get_text_preview_with_status(path, max_chars)`

For Google stubs it calls `_google_preview_and_status()` which:

1) parses stub JSON and emits a header (title/mime/url/id when present)
2) attempts export (except `.gform`)
3) returns `(preview_text, status)` where status includes:
   - `is_google: True`
   - `google_fetched: True/False` (whether export succeeded)
   - `is_essentially_empty: True/False` (used to decide whether to skip)

Key behavior to recreate:

- If export succeeds, preview becomes: `header + "\n\n" + exported_text`.
- If export fails, preview is only the header.
- If the stub contains almost no metadata, the code falls back to a minimal hint like:
  `title: <filename> (Google link; no local content)` and marks it “essentially empty”.

## Minimal runnable example (recreate outside this project)

This example mirrors the implementation closely. It reads a `.gdoc/.gsheet` stub on disk and prints the exported preview.

```py
import os
from pathlib import Path

from ai_folder_sorter.utils import get_text_preview_with_status

# 1) Configure OAuth (recommended)
# os.environ["GOOGLE_OAUTH_CLIENT_FILE"] = "/absolute/path/to/client_secret.json"
# os.environ["GOOGLE_OAUTH_TOKEN_FILE"] = "/absolute/path/to/token.json"  # optional

stub = Path("/path/to/some-document.gdoc")
text, status = get_text_preview_with_status(stub, max_chars=20_000)

print(status)
print(text)
```

If `GOOGLE_OAUTH_CLIENT_FILE` is set and a token doesn’t exist yet, the first run will open a browser for consent and create the token file.

## Common issues & fixes

### 0) Google client libraries not installed

Symptoms:

- Export always fails, `google_fetched` stays `False`
- You may see `ImportError`/`ModuleNotFoundError` for `googleapiclient` or `google_auth_oauthlib`

Fix:

- Install deps: `pip install -r requirements.txt`

### 1) No credentials available (preview only contains header)

Symptoms:

- `google_fetched` is `False`
- logs show `google_resolve_no_creds`

Fix options:

- Set `GOOGLE_OAUTH_CLIENT_FILE` to a valid installed-app client secret JSON
- Or configure ADC via `gcloud auth application-default login`

### 2) “Refresh token missing” or repeated consent prompts

Cause:

- Token cache exists but doesn’t include a refresh token, or consent wasn’t granted for offline access.

Fix:

- Delete the cached token file and re-run; the code uses `access_type="offline"` and `prompt="consent"` to request refresh tokens.

### 2b) Localhost callback issues (browser flow hangs or cannot connect)

Cause:

- The installed-app flow runs a temporary HTTP server on `localhost` (random free port) to receive the OAuth callback.

Fix:

- Ensure your firewall/VPN isn’t blocking local loopback connections.
- If needed, replace `run_local_server(...)` with `run_console()` (manual copy/paste auth code) for headless environments.

### 3) 403 / insufficientPermissions

Cause:

- OAuth scopes too narrow or account lacks access.

Fix:

- Ensure scope includes `https://www.googleapis.com/auth/drive.readonly` (this project uses exactly that)
- Ensure the authenticated user/service account can access the file

### 4) Shared Drives / Team Drives access issues

Symptom:

- 404 for files you can see in the UI, or export fails in shared drives.

Potential fix (not currently implemented here):

Add `supportsAllDrives=True` to Drive calls, e.g.:

```py
service.files().export(
    fileId=file_id,
    mimeType=mime,
    supportsAllDrives=True,
).execute()

service.files().get(
    fileId=file_id,
    fields="modifiedTime,mimeType",
    supportsAllDrives=True,
).execute()
```

### 5) `.gslides` export returns empty / fails

Reason:

- This implementation exports non-sheets as `text/plain`. Google Slides often doesn’t export meaningfully to `text/plain`.

Fix (recommended approach):

- Export Slides to PPTX (`application/vnd.openxmlformats-officedocument.presentationml.presentation`) or PDF, then extract text. That requires changing the export MIME based on the Drive file’s `mimeType`.

### 6) `.gform` has no body content

Reason:

- The code intentionally does **not** attempt a Drive export for Forms.

What you can do instead:

- Use the Forms API (separate API) or treat the stub metadata (title + URL) as the preview.

## Security notes

- Never commit `client_secret*.json` or `token.json`.
- Keep `GOOGLE_OAUTH_TOKEN_FILE` in a private location.
- The scope is read-only (`drive.readonly`) to reduce blast radius.
