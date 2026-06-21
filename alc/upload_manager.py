"""Session-scoped upload handling for the public ALC scoreboard app.

Uploaded files are written to a unique temporary folder for the current
Streamlit session. They are runtime files only: nothing is committed to the
repository and another browser session receives a different folder.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st


UPLOAD_ROOT = Path(tempfile.gettempdir()) / "alc_scoreboard_uploads"
STALE_UPLOAD_MAX_AGE_SECONDS = 24 * 60 * 60

WORKBOOK_EXTENSIONS = {".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}

SLOT_EXTENSIONS = {
    "votes": WORKBOOK_EXTENSIONS,
    "elements": WORKBOOK_EXTENSIONS,
    "background": IMAGE_EXTENSIONS,
    "logo": IMAGE_EXTENSIONS,
    "backsound": AUDIO_EXTENSIONS,
}

SLOT_SIZE_LIMITS = {
    "votes": 25 * 1024 * 1024,
    "elements": 25 * 1024 * 1024,
    "background": 30 * 1024 * 1024,
    "logo": 15 * 1024 * 1024,
    "backsound": 50 * 1024 * 1024,
}

UPLOAD_WIDGET_KEYS = (
    "setup_votes_upload",
    "setup_elements_upload",
    "setup_background_upload",
    "setup_logo_upload",
    "setup_backsound_upload",
)

APP_STATE_KEYS_TO_RESET = (
    "totals",
    "voter_idx",
    "point_idx",
    "group_idx",
    "revealed_log",
    "hod_revealed",
    "fly_entries",
    "animation_nonce",
    "animation_snapshot",
    "animation_locked_until",
    "entered_voting_arena",
    "show_final_standing",
    "arena_entry_animation",
    "page_entry_animation_nonce",
    "landing_entry_animation",
    "app_mode",
    "rehearsal_no_animation",
    "rehearsal_vote_selector",
    "rehearsal_checkpoint",
)


def _cleanup_stale_upload_directories() -> None:
    """Best-effort cleanup for abandoned temporary sessions."""
    try:
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - STALE_UPLOAD_MAX_AGE_SECONDS
        for candidate in UPLOAD_ROOT.iterdir():
            try:
                if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                    shutil.rmtree(candidate, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def initialize_upload_state() -> None:
    """Create upload-related session keys without touching live vote progress."""
    if "upload_cleanup_done" not in st.session_state:
        _cleanup_stale_upload_directories()
        st.session_state.upload_cleanup_done = True

    if "upload_session_id" not in st.session_state:
        st.session_state.upload_session_id = uuid.uuid4().hex
    if "edition_loaded" not in st.session_state:
        st.session_state.edition_loaded = False

    for slot in SLOT_EXTENSIONS:
        for suffix in ("path", "hash", "name"):
            key = f"upload_{slot}_{suffix}"
            if key not in st.session_state:
                st.session_state[key] = ""
        active_key = f"active_{slot}_path"
        if active_key not in st.session_state:
            st.session_state[active_key] = ""


def get_session_upload_dir() -> Path:
    initialize_upload_state()
    directory = UPLOAD_ROOT / str(st.session_state.upload_session_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _remove_path(value: str) -> None:
    if not value:
        return
    try:
        path = Path(value)
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def sync_uploaded_file(uploaded_file, slot: str) -> tuple[str, list[str]]:
    """Persist one uploader value and return ``(path, errors)``.

    When the uploader is cleared while still on the setup screen, the matching
    temporary file and state are cleared too.
    """
    if slot not in SLOT_EXTENSIONS:
        raise ValueError(f"Unknown upload slot: {slot}")

    initialize_upload_state()
    path_key = f"upload_{slot}_path"
    hash_key = f"upload_{slot}_hash"
    name_key = f"upload_{slot}_name"

    if uploaded_file is None:
        _remove_path(st.session_state.get(path_key, ""))
        st.session_state[path_key] = ""
        st.session_state[hash_key] = ""
        st.session_state[name_key] = ""
        return "", []

    original_name = Path(str(getattr(uploaded_file, "name", ""))).name
    extension = Path(original_name).suffix.lower()
    allowed = SLOT_EXTENSIONS[slot]
    if extension not in allowed:
        allowed_label = ", ".join(sorted(item.lstrip(".").upper() for item in allowed))
        return "", [f"{slot.title()} must use one of these formats: {allowed_label}."]

    try:
        payload = uploaded_file.getvalue()
    except Exception as exc:
        return "", [f"Could not read the uploaded {slot} file: {exc}"]

    if not payload:
        return "", [f"The uploaded {slot} file is empty."]

    size_limit = SLOT_SIZE_LIMITS[slot]
    if len(payload) > size_limit:
        limit_mb = size_limit // (1024 * 1024)
        return "", [f"The uploaded {slot} file exceeds the {limit_mb} MB limit."]

    digest = hashlib.sha256(payload).hexdigest()
    previous_path = st.session_state.get(path_key, "")
    if (
        st.session_state.get(hash_key) == digest
        and previous_path
        and Path(previous_path).exists()
    ):
        return previous_path, []

    directory = get_session_upload_dir()
    destination = directory / f"{slot}_{digest[:16]}{extension}"
    temporary = directory / f".{destination.name}.tmp"

    try:
        temporary.write_bytes(payload)
        temporary.replace(destination)
    except OSError as exc:
        return "", [f"Could not store the uploaded {slot} file: {exc}"]

    if previous_path and Path(previous_path) != destination:
        _remove_path(previous_path)

    st.session_state[path_key] = str(destination)
    st.session_state[hash_key] = digest
    st.session_state[name_key] = original_name
    return str(destination), []


def active_upload_paths() -> dict[str, str]:
    initialize_upload_state()
    return {
        slot: str(st.session_state.get(f"active_{slot}_path", "") or "")
        for slot in SLOT_EXTENSIONS
    }


def activate_uploaded_edition(paths: dict[str, str]) -> None:
    """Promote validated setup files to the active scoreboard edition."""
    initialize_upload_state()
    for slot in SLOT_EXTENSIONS:
        st.session_state[f"active_{slot}_path"] = str(paths.get(slot, "") or "")

    st.session_state.edition_loaded = True

    # A newly activated edition must always start from a clean vote state.
    for key in APP_STATE_KEYS_TO_RESET:
        if key in st.session_state:
            del st.session_state[key]


def reset_uploaded_edition() -> None:
    """Return to setup and remove all files belonging to this session."""
    initialize_upload_state()
    session_dir = UPLOAD_ROOT / str(st.session_state.upload_session_id)
    shutil.rmtree(session_dir, ignore_errors=True)

    for slot in SLOT_EXTENSIONS:
        st.session_state[f"upload_{slot}_path"] = ""
        st.session_state[f"upload_{slot}_hash"] = ""
        st.session_state[f"upload_{slot}_name"] = ""
        st.session_state[f"active_{slot}_path"] = ""

    for key in APP_STATE_KEYS_TO_RESET:
        if key in st.session_state:
            del st.session_state[key]

    for key in UPLOAD_WIDGET_KEYS:
        if key in st.session_state:
            del st.session_state[key]

    st.session_state.edition_loaded = False
    st.session_state.upload_session_id = uuid.uuid4().hex


def validate_saved_media(path_value: str, slot: str) -> tuple[list[str], list[str]]:
    """Run lightweight validation for an optional uploaded media file."""
    errors: list[str] = []
    warnings: list[str] = []

    if not path_value:
        return errors, warnings

    path = Path(path_value)
    if not path.exists() or not path.is_file():
        errors.append(f"Uploaded {slot} file could not be found in the current session.")
        return errors, warnings

    extension = path.suffix.lower()
    if extension not in SLOT_EXTENSIONS.get(slot, set()):
        errors.append(f"Uploaded {slot} has an unsupported file extension: {extension or '(none)'}.")

    try:
        if path.stat().st_size <= 0:
            errors.append(f"Uploaded {slot} file is empty.")
    except OSError as exc:
        errors.append(f"Uploaded {slot} metadata could not be read: {exc}")

    return errors, warnings
