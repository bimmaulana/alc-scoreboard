# =============================================================================
# 1. IMPORTS AND COMPATIBILITY CONFIG
# =============================================================================

import html
import json
import re
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from alc.config import ANIMATION, POINTS_ORDER, REVEAL_GROUPS

# GEOMETRY was introduced in Stage 6. Keep the main app compatible with an
# older alc/config.py so a mismatched file copy cannot stop the scoreboard.
try:
    from alc.config import GEOMETRY
except ImportError:
    class _FallbackGeometry:
        scoreboard_columns = 4
        rows_per_column = 10

        wrapper_padding_left_px = 16
        wrapper_padding_right_px = 24
        grid_gap_px = 22

        row_height_px = 52
        row_gap_px = 11
        rank_column_width_px = 36
        flag_track_width_px = 70
        points_box_width_px = 58
        pad_height_px = 37
        flag_width_px = 50
        flag_height_px = 37

        point_first_row_count = 7
        point_bubble_size_px = 29
        point_column_gap_px = 8
        point_row_gap_px = 10

        flying_ball_size_px = 38
        country_landing_x_ratio = 0.72
        country_landing_y_ratio = 0.50

        point_viewport_fallback_x_ratio = 0.89
        point_viewport_fallback_y_ratio = 0.86
        country_viewport_fallback_x_ratio = 0.18
        country_viewport_fallback_y_ratio = 0.38

        @property
        def row_step_px(self):
            return self.row_height_px + self.row_gap_px

        @property
        def column_translation_extra_px(self):
            return self.rank_column_width_px + self.grid_gap_px

        @property
        def point_center_offset_px(self):
            return self.point_bubble_size_px / 2

        @property
        def point_column_step_px(self):
            return self.point_bubble_size_px + self.point_column_gap_px

        @property
        def point_row_step_px(self):
            return self.point_bubble_size_px + self.point_row_gap_px

    GEOMETRY = _FallbackGeometry()
from alc.flag_loader import (
    FLAG_LOADER_VERSION, WorkbookLoadError,
    build_palette_css_variables, clean_text, flag_html, hex_to_rgba,
    image_to_data_uri, load_data, load_palette, load_title,
)
from alc.export import (
    build_complete_vote_data as build_complete_vote_data_from_source,
    build_result_excel_bytes as build_result_excel_bytes_from_source,
)
from alc.ranking import build_ranking_dataframe
from alc.flag_validation import (
    validate_elements_data, validate_required_sheets, validate_workbook_data,
)
from alc.diagnostics import run_startup_diagnostics
from alc.upload_manager import (
    activate_uploaded_edition, active_upload_paths, initialize_upload_state,
    reset_uploaded_edition, sync_uploaded_file, validate_saved_media,
)
from components.audio import render_bgm_controller
from alc.state import (
    animation_is_active, clear_animation_state, current_voter,
    enter_voting_arena, initialize_session_state, open_final_standing,
    pending_animation_duration_ms, reset_all, reveal_next, undo_last,
    vote_recipient,
)


# =============================================================================
# 2. STREAMLIT APP SETUP AND PROJECT PATHS
# =============================================================================

st.set_page_config(page_title="Allegro LINE Contest Result", layout="wide")


REHEARSAL_CHECKPOINT_KEYS = (
    "totals",
    "voter_idx",
    "point_idx",
    "group_idx",
    "revealed_log",
    "hod_revealed",
)


def save_rehearsal_checkpoint():
    """Save only Rehearsal voting progress for this uploaded edition."""
    clear_animation_state()
    checkpoint = {
        key: deepcopy(st.session_state.get(key))
        for key in REHEARSAL_CHECKPOINT_KEYS
    }
    checkpoint["rehearsal_no_animation"] = bool(
        st.session_state.get("rehearsal_no_animation", False)
    )
    st.session_state.rehearsal_checkpoint = checkpoint


def restore_rehearsal_checkpoint():
    """Restore Rehearsal progress without carrying over Production state."""
    checkpoint = st.session_state.get("rehearsal_checkpoint")
    reset_all()

    if isinstance(checkpoint, dict):
        for key in REHEARSAL_CHECKPOINT_KEYS:
            if key in checkpoint:
                st.session_state[key] = deepcopy(checkpoint[key])
        st.session_state.rehearsal_no_animation = bool(
            checkpoint.get("rehearsal_no_animation", False)
        )
    else:
        st.session_state.rehearsal_no_animation = False

    clear_animation_state()
    st.session_state.show_final_standing = False
    st.session_state.rehearsal_vote_selector = int(
        st.session_state.get("voter_idx", 0) or 0
    )


def reset_production_progress():
    """Production never resumes a previous checkpoint."""
    reset_all()
    clear_animation_state()
    st.session_state.rehearsal_vote_selector = 0


def go_home():
    """Return Home, checkpointing Rehearsal but discarding Production progress."""
    current_mode = st.session_state.get("app_mode")
    if current_mode == "rehearsal":
        save_rehearsal_checkpoint()
    elif current_mode == "production":
        reset_production_progress()
    else:
        clear_animation_state()

    st.session_state.app_mode = None
    st.session_state.entered_voting_arena = False
    st.session_state.show_final_standing = False
    st.session_state.landing_entry_animation = True
    st.session_state.page_entry_animation_nonce = int(
        st.session_state.get("page_entry_animation_nonce", 0) or 0
    ) + 1


def request_final_jpg_download():
    """Request one browser-side JPG export of the current Final Standing."""
    st.session_state.final_jpg_download_requested = True


# Project root containing templates, references, UI assets, and modules.
BASE_DIR = Path(__file__).resolve().parent


# =============================================================================
# 3. STATIC UI ASSET CACHE AND SAFE SERIALIZATION
# =============================================================================

@st.cache_data(show_spinner=False)
def _read_text_asset_cached(asset_path, file_mtime_ns, file_size):
    """Read one static CSS/JS asset; metadata arguments invalidate the cache."""
    # file_mtime_ns and file_size intentionally participate in Streamlit's
    # cache key. Their values do not need to be used inside the function.
    return Path(asset_path).read_text(encoding="utf-8")


def load_text_asset(relative_path):
    """Load a required CSS/JS asset with automatic cache invalidation."""
    path = BASE_DIR / relative_path
    if not path.exists():
        st.error(f"Required UI asset not found: {path}")
        st.stop()

    try:
        stat = path.stat()
    except OSError as exc:
        st.error(f"Could not read required UI asset metadata: {path} ({exc})")
        st.stop()

    return _read_text_asset_cached(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


def escape_html_text(value):
    """Escape workbook text before inserting it into HTML text/attributes."""
    return html.escape(clean_text(value), quote=True)


def json_for_inline_script(value):
    """Serialize data safely for embedding inside an inline <script> block."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def scope_scoreboard_css_for_native(css_text, root_selector="#alc-scoreboard-root"):
    """Scope scoreboard CSS for direct, non-iframe rendering with ``st.html``."""
    css_text = str(css_text).replace("__PALETTE_CSS_VARS__", "")
    css_text = re.sub(r"@import\s+url\([^;]+;\s*", "", css_text, flags=re.I)
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)

    def scoped_selector(selector):
        selector = selector.strip()
        if not selector:
            return []
        if selector == "*":
            return [root_selector, f"{root_selector} *"]
        if selector in {"html", "body", ":root"}:
            return [root_selector]
        for prefix in ("html ", "body ", ":root "):
            if selector.startswith(prefix):
                return [f"{root_selector} {selector[len(prefix):].strip()}"]
        return [f"{root_selector} {selector}"]

    output = []
    cursor = 0
    length = len(css_text)
    while cursor < length:
        brace_start = css_text.find("{", cursor)
        if brace_start < 0:
            tail = css_text[cursor:].strip()
            if tail:
                output.append(tail)
            break

        header = css_text[cursor:brace_start].strip()
        depth = 1
        pos = brace_start + 1
        while pos < length and depth:
            if css_text[pos] == "{":
                depth += 1
            elif css_text[pos] == "}":
                depth -= 1
            pos += 1
        if depth:
            raise RuntimeError("Unbalanced braces in scoreboard CSS.")

        body = css_text[brace_start + 1:pos - 1]
        lower_header = header.lower()
        if lower_header.startswith("@keyframes") or lower_header.startswith("@-webkit-keyframes"):
            output.append(f"{header} {{{body}}}")
        elif header.startswith("@"):
            output.append(f"{header} {{{body}}}")
        else:
            scoped = []
            for selector in header.split(","):
                scoped.extend(scoped_selector(selector))
            if scoped:
                output.append(f"{', '.join(scoped)} {{{body}}}")
        cursor = pos

    return "\n".join(output)


# =============================================================================
# 4. SCOREBOARD GEOMETRY AND ANIMATION-JS HELPERS
# =============================================================================

def build_scoreboard_geometry_css():
    """Override live scoreboard dimensions from the central geometry config."""
    g = GEOMETRY
    return f"""
    .wrapper {{
        padding-left: {g.wrapper_padding_left_px}px;
        padding-right: {g.wrapper_padding_right_px}px;
    }}
    .score-grid {{
        grid-template-columns: repeat({g.scoreboard_columns}, minmax(0, 1fr));
        gap: {g.grid_gap_px}px;
    }}
    .score-row {{
        height: {g.row_height_px}px;
        grid-template-columns: {g.rank_column_width_px}px minmax(0, 1fr);
        margin-bottom: {g.row_gap_px}px;
    }}
    .moving-pad {{
        grid-template-columns: {g.flag_track_width_px}px minmax(0, 1fr) {g.points_box_width_px}px;
    }}
    .flag-circle {{
        width: {g.flag_width_px}px;
        height: {g.flag_height_px}px;
    }}
    .country-bar {{ height: {g.pad_height_px}px; }}
    .points-box {{
        height: {g.pad_height_px}px;
        width: {g.points_box_width_px}px;
        min-width: {g.points_box_width_px}px;
        max-width: {g.points_box_width_px}px;
        flex-basis: {g.points_box_width_px}px;
    }}
    """


def build_point_pad_geometry_css():
    """Keep the point-pad CSS aligned with JavaScript fallback calculations."""
    g = GEOMETRY
    return f"""
    .point-pad {{
        column-gap: {g.point_column_gap_px}px;
        row-gap: {g.point_row_gap_px}px;
    }}
    .point-bubble {{
        width: {g.point_bubble_size_px}px;
        height: {g.point_bubble_size_px}px;
    }}
    """


def _replace_required(source, old, new, label):
    """Replace one known JS fragment and fail loudly if the asset drifted."""
    occurrences = source.count(old)
    if occurrences != 1:
        raise RuntimeError(
            f"Animation geometry injection failed for {label}: "
            f"expected 1 match, found {occurrences}."
        )
    return source.replace(old, new, 1)


def inject_animation_geometry(js_source):
    """Inject central geometry values into the existing animation JavaScript."""
    g = GEOMETRY
    geometry_payload = {
        "scoreboardColumns": g.scoreboard_columns,
        "rowsPerColumn": g.rows_per_column,
        "wrapperPaddingLeftPx": g.wrapper_padding_left_px,
        "wrapperPaddingRightPx": g.wrapper_padding_right_px,
        "gridGapPx": g.grid_gap_px,
        "rowHeightPx": g.row_height_px,
        "rowStepPx": g.row_step_px,
        "rankColumnWidthPx": g.rank_column_width_px,
        "pointFirstRowCount": g.point_first_row_count,
        "pointCenterOffsetPx": g.point_center_offset_px,
        "pointColumnStepPx": g.point_column_step_px,
        "pointRowStepPx": g.point_row_step_px,
        "flyingBallSizePx": g.flying_ball_size_px,
        "countryLandingXRatio": g.country_landing_x_ratio,
        "countryLandingYRatio": g.country_landing_y_ratio,
        "pointViewportFallbackXRatio": g.point_viewport_fallback_x_ratio,
        "pointViewportFallbackYRatio": g.point_viewport_fallback_y_ratio,
        "countryViewportFallbackXRatio": g.country_viewport_fallback_x_ratio,
        "countryViewportFallbackYRatio": g.country_viewport_fallback_y_ratio,
        "pointsOrder": POINTS_ORDER,
    }
    geometry_json = json.dumps(geometry_payload, separators=(",", ":"))

    js_source = _replace_required(
        js_source,
        "const badgeEarlyOffsetMs = __BADGE_EARLY_OFFSET_MS__;",
        "const badgeEarlyOffsetMs = __BADGE_EARLY_OFFSET_MS__;\n"
        f"    const geometry = {geometry_json};",
        "geometry payload",
    )
    js_source = _replace_required(
        js_source,
        "width: 38px; height: 38px;",
        "width: ${geometry.flyingBallSizePx}px; height: ${geometry.flyingBallSizePx}px;",
        "flying ball size",
    )
    js_source = _replace_required(
        js_source,
        "const order = [1,2,3,4,5,6,7,8,10,12,14,17,20];",
        "const order = geometry.pointsOrder;",
        "point order",
    )
    js_source = _replace_required(
        js_source,
        "const col = idx <= 6 ? idx : idx - 7;",
        "const col = idx < geometry.pointFirstRowCount ? idx : idx - geometry.pointFirstRowCount;",
        "point fallback column",
    )
    js_source = _replace_required(
        js_source,
        "const row = idx <= 6 ? 0 : 1;",
        "const row = idx < geometry.pointFirstRowCount ? 0 : 1;",
        "point fallback row",
    )
    js_source = _replace_required(
        js_source,
        "return { x: pr.left + 14.5 + col * 37, y: pr.top + 14.5 + row * 39 };",
        "return {\n"
        "                x: pr.left + geometry.pointCenterOffsetPx + col * geometry.pointColumnStepPx,\n"
        "                y: pr.top + geometry.pointCenterOffsetPx + row * geometry.pointRowStepPx\n"
        "            };",
        "point fallback coordinates",
    )
    js_source = _replace_required(
        js_source,
        "return { x: window.innerWidth * 0.89, y: window.innerHeight * 0.86 };",
        "return {\n"
        "            x: window.parent.innerWidth * geometry.pointViewportFallbackXRatio,\n"
        "            y: window.parent.innerHeight * geometry.pointViewportFallbackYRatio\n"
        "        };",
        "point viewport fallback",
    )
    js_source = _replace_required(
        js_source,
        "x: fr.left + tr.left + (tr.width * 0.72),\n                    y: fr.top + tr.top + (tr.height * 0.50)",
        "x: fr.left + tr.left + (tr.width * geometry.countryLandingXRatio),\n"
        "                    y: fr.top + tr.top + (tr.height * geometry.countryLandingYRatio)",
        "country DOM landing ratio",
    )

    old_country_fallback = (
        "        const col = Math.floor(slot / 10);\n"
        "        const row = slot % 10;\n"
        "        const frame = frames[0];\n"
        "        if (frame) {\n"
        "            const fr = frame.getBoundingClientRect();\n"
        "            return { x: fr.left + 82 + col * 286 + 170, y: fr.top + 29 + row * 63 + 19 };\n"
        "        }\n"
    )
    new_country_fallback = (
        "        const col = Math.floor(slot / geometry.rowsPerColumn);\n"
        "        const row = slot % geometry.rowsPerColumn;\n"
        "        const frame = frames[0];\n"
        "        if (frame) {\n"
        "            const fr = frame.getBoundingClientRect();\n"
        "            const innerWidth = Math.max(\n"
        "                0,\n"
        "                fr.width - geometry.wrapperPaddingLeftPx - geometry.wrapperPaddingRightPx\n"
        "            );\n"
        "            const columnWidth = (\n"
        "                innerWidth - ((geometry.scoreboardColumns - 1) * geometry.gridGapPx)\n"
        "            ) / geometry.scoreboardColumns;\n"
        "            const movingPadWidth = Math.max(\n"
        "                0,\n"
        "                columnWidth - geometry.rankColumnWidthPx\n"
        "            );\n"
        "            return {\n"
        "                x: fr.left\n"
        "                    + geometry.wrapperPaddingLeftPx\n"
        "                    + (col * (columnWidth + geometry.gridGapPx))\n"
        "                    + geometry.rankColumnWidthPx\n"
        "                    + (movingPadWidth * geometry.countryLandingXRatio),\n"
        "                y: fr.top\n"
        "                    + (row * geometry.rowStepPx)\n"
        "                    + (geometry.rowHeightPx * geometry.countryLandingYRatio)\n"
        "            };\n"
        "        }\n"
    )
    js_source = _replace_required(
        js_source,
        old_country_fallback,
        new_country_fallback,
        "country frame fallback",
    )
    js_source = _replace_required(
        js_source,
        "return { x: window.innerWidth * 0.18, y: window.innerHeight * 0.38 };",
        "return {\n"
        "            x: window.parent.innerWidth * geometry.countryViewportFallbackXRatio,\n"
        "            y: window.parent.innerHeight * geometry.countryViewportFallbackYRatio\n"
        "        };",
        "country viewport fallback",
    )
    return js_source

# =============================================================================
# 5. PUBLIC SETUP, UPLOADED WORKBOOKS, MEDIA, AND VALIDATION
# =============================================================================

initialize_upload_state()

TEMPLATE_VOTES_FILE = BASE_DIR / "templates" / "ALC_Votes.xlsx"
TEMPLATE_ELEMENTS_FILE = BASE_DIR / "templates" / "ALC_Elements.xlsx"
FLAG_REFERENCE_FILE = BASE_DIR / "references" / "ALC_Flag_Codes.xlsx"


@st.cache_data(show_spinner=False)
def _read_binary_asset_cached(asset_path, file_mtime_ns, file_size):
    """Read a downloadable template/reference file with cache invalidation."""
    return Path(asset_path).read_bytes()


def read_binary_asset(path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return b""
    try:
        stat = path.stat()
        return _read_binary_asset_cached(
            str(path.resolve()),
            stat.st_mtime_ns,
            stat.st_size,
        )
    except OSError:
        return b""


def file_signature(path_value):
    """Return cheap metadata used to invalidate workbook/media caches."""
    if not path_value:
        return 0, 0
    try:
        stat = Path(path_value).stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return 0, 0


@st.cache_data(show_spinner=False)
def validate_required_sheets_cached(
    votes_file,
    votes_mtime_ns,
    votes_size,
    elements_file,
    elements_mtime_ns,
    elements_size,
    loader_version,
):
    """Cache the split-workbook sheet check until either upload changes."""
    return validate_required_sheets(votes_file, elements_file)


@st.cache_data(show_spinner=False)
def load_workbook_static_data_cached(
    votes_file,
    votes_mtime_ns,
    votes_size,
    elements_file,
    elements_mtime_ns,
    elements_size,
    loader_version,
):
    """Read both uploaded workbooks once and reuse them across reruns."""
    title, host = load_title(elements_file)
    palette = load_palette(elements_file)
    data = load_data(votes_file)
    return (title, host, palette, *data)


def _deduplicate_messages(messages):
    return list(dict.fromkeys(message for message in messages if message))


def validate_uploaded_edition(paths):
    """Validate setup uploads without activating or mutating vote progress."""
    errors = []
    warnings = []
    package = None

    votes_file = paths.get("votes", "")
    elements_file = paths.get("elements", "")
    votes_mtime_ns, votes_size = file_signature(votes_file)
    elements_mtime_ns, elements_size = file_signature(elements_file)

    errors.extend(
        validate_required_sheets_cached(
            votes_file,
            votes_mtime_ns,
            votes_size,
            elements_file,
            elements_mtime_ns,
            elements_size,
            FLAG_LOADER_VERSION,
        )
    )

    for slot in ("background", "logo", "backsound"):
        media_errors, media_warnings = validate_saved_media(paths.get(slot, ""), slot)
        errors.extend(media_errors)
        warnings.extend(media_warnings)

    if errors:
        return _deduplicate_messages(errors), _deduplicate_messages(warnings), package

    try:
        package = load_workbook_static_data_cached(
            votes_file,
            votes_mtime_ns,
            votes_size,
            elements_file,
            elements_mtime_ns,
            elements_size,
            FLAG_LOADER_VERSION,
        )
    except WorkbookLoadError as exc:
        errors.append(str(exc))
        return _deduplicate_messages(errors), _deduplicate_messages(warnings), None
    except Exception as exc:
        errors.append(f"Uploaded edition could not be loaded: {exc}")
        return _deduplicate_messages(errors), _deduplicate_messages(warnings), None

    (
        title,
        host,
        palette,
        participants,
        country_info,
        votes,
        voting_countries,
        point_to_row,
        voter_col_by_country,
    ) = package

    element_errors, element_warnings = validate_elements_data(title, host)
    errors.extend(element_errors)
    warnings.extend(element_warnings)

    qc_errors, qc_warnings = validate_workbook_data(
        participants=participants,
        country_info=country_info,
        votes=votes,
        voting_countries=voting_countries,
        point_to_row=point_to_row,
        voter_col_by_country=voter_col_by_country,
        background_file=paths.get("background", ""),
        logo_file=paths.get("logo", ""),
        backsound_file=paths.get("backsound", ""),
        base_dir=Path(votes_file).parent,
    )
    errors.extend(qc_errors)
    warnings.extend(qc_warnings)

    diagnostic_errors, diagnostic_warnings = run_startup_diagnostics(
        base_dir=BASE_DIR,
        votes_file=votes_file,
        elements_file=elements_file,
        participant_count=len(participants),
        voter_count=len(voting_countries),
        geometry=GEOMETRY,
        animation=ANIMATION,
        points_order=POINTS_ORDER,
        reveal_groups=REVEAL_GROUPS,
        background_file=paths.get("background", ""),
        logo_file=paths.get("logo", ""),
        backsound_file=paths.get("backsound", ""),
    )
    errors.extend(diagnostic_errors)
    warnings.extend(diagnostic_warnings)

    return _deduplicate_messages(errors), _deduplicate_messages(warnings), package


def render_upload_setup():
    """Render the first page of the deployed app and stop until activation."""
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 2.3rem;
            padding-bottom: 3rem;
        }
        .alc-setup-hero {
            padding: 26px 30px 24px;
            border-radius: 22px;
            background: linear-gradient(135deg, #071735 0%, #15395B 65%, #1F4E78 100%);
            border: 1px solid rgba(244,200,79,.68);
            box-shadow: 0 18px 50px rgba(0,0,0,.22);
            margin-bottom: 22px;
        }
        .alc-setup-kicker {
            color: #F4C84F;
            font-size: .82rem;
            font-weight: 800;
            letter-spacing: .22em;
            text-transform: uppercase;
            margin-bottom: 7px;
        }
        .alc-setup-title {
            color: #FFFFFF;
            font-size: 2rem;
            font-weight: 850;
            line-height: 1.12;
            margin-bottom: 8px;
        }
        .alc-setup-copy {
            color: rgba(255,255,255,.82);
            font-size: .98rem;
            max-width: 780px;
        }
        .alc-setup-section {
            margin-top: 14px;
            margin-bottom: 4px;
            font-size: 1.05rem;
            font-weight: 800;
            letter-spacing: .03em;
        }
        .alc-required { color: #B42318; font-weight: 700; }
        .alc-optional { color: #667085; font-weight: 600; }
        .alc-ready-card {
            padding: 17px 20px;
            border: 1px solid #ABEFC6;
            border-radius: 14px;
            background: #ECFDF3;
            color: #067647;
            margin: 12px 0;
        }
        </style>
        <div class="alc-setup-hero">
            <div class="alc-setup-kicker">ALC SCOREBOARD</div>
            <div class="alc-setup-title">SET UP YOUR EDITION</div>
            <div class="alc-setup-copy">
                Download the empty formats, fill them in, then upload your two workbooks.
                Background, logo, and backsound are optional.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="alc-setup-section">1. DOWNLOAD THE FORMATS</div>', unsafe_allow_html=True)
    download_columns = st.columns(3, gap="small")
    with download_columns[0]:
        votes_template_bytes = read_binary_asset(TEMPLATE_VOTES_FILE)
        st.download_button(
            "DOWNLOAD VOTES FORMAT",
            data=votes_template_bytes,
            file_name="ALC_Votes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=not bool(votes_template_bytes),
        )
    with download_columns[1]:
        elements_template_bytes = read_binary_asset(TEMPLATE_ELEMENTS_FILE)
        st.download_button(
            "DOWNLOAD ELEMENTS FORMAT",
            data=elements_template_bytes,
            file_name="ALC_Elements.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=not bool(elements_template_bytes),
        )
    with download_columns[2]:
        reference_bytes = read_binary_asset(FLAG_REFERENCE_FILE)
        st.download_button(
            "DOWNLOAD FLAG CODES",
            data=reference_bytes,
            file_name="ALC_Flag_Codes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=not bool(reference_bytes),
        )

    st.markdown('<div class="alc-setup-section">2. UPLOAD YOUR EDITION</div>', unsafe_allow_html=True)
    required_columns = st.columns(2, gap="medium")
    with required_columns[0]:
        st.markdown('**Votes workbook** <span class="alc-required">Required</span>', unsafe_allow_html=True)
        votes_upload = st.file_uploader(
            "Participants + Votes",
            type=["xlsx"],
            key="setup_votes_upload",
            label_visibility="collapsed",
        )
    with required_columns[1]:
        st.markdown('**Elements workbook** <span class="alc-required">Required</span>', unsafe_allow_html=True)
        elements_upload = st.file_uploader(
            "Elements + Palette",
            type=["xlsx"],
            key="setup_elements_upload",
            label_visibility="collapsed",
        )

    optional_columns = st.columns(3, gap="medium")
    with optional_columns[0]:
        st.markdown('**Background** <span class="alc-optional">Optional</span>', unsafe_allow_html=True)
        background_upload = st.file_uploader(
            "Background",
            type=["png", "jpg", "jpeg", "webp", "svg"],
            key="setup_background_upload",
            label_visibility="collapsed",
        )
    with optional_columns[1]:
        st.markdown('**Logo** <span class="alc-optional">Optional</span>', unsafe_allow_html=True)
        logo_upload = st.file_uploader(
            "Logo",
            type=["png", "jpg", "jpeg", "webp", "svg"],
            key="setup_logo_upload",
            label_visibility="collapsed",
        )
    with optional_columns[2]:
        st.markdown('**Backsound** <span class="alc-optional">Optional</span>', unsafe_allow_html=True)
        backsound_upload = st.file_uploader(
            "Backsound",
            type=["mp3", "wav", "ogg", "m4a", "aac"],
            key="setup_backsound_upload",
            label_visibility="collapsed",
        )

    upload_values = {
        "votes": votes_upload,
        "elements": elements_upload,
        "background": background_upload,
        "logo": logo_upload,
        "backsound": backsound_upload,
    }
    paths = {}
    upload_errors = []
    for slot, uploaded_file in upload_values.items():
        path_value, slot_errors = sync_uploaded_file(uploaded_file, slot)
        paths[slot] = path_value
        upload_errors.extend(slot_errors)

    st.markdown('<div class="alc-setup-section">3. CHECK & LAUNCH</div>', unsafe_allow_html=True)

    if upload_errors:
        st.error("UPLOAD CHECK FAILED")
        for error in _deduplicate_messages(upload_errors):
            st.write(f"• {error}")
        st.stop()

    if not paths["votes"] or not paths["elements"]:
        st.info("Upload both required workbooks to run the scoreboard check.")
        st.stop()

    with st.spinner("Checking workbooks and edition files..."):
        setup_errors, setup_warnings, package = validate_uploaded_edition(paths)

    if setup_errors:
        st.error(
            f"EDITION CHECK FAILED — {len(setup_errors)} problem(s) must be fixed."
        )
        with st.expander("VIEW EDITION CHECK REPORT", expanded=True):
            for error in setup_errors:
                st.write(f"• {error}")
            if setup_warnings:
                st.markdown("**Warnings**")
                for warning in setup_warnings:
                    st.write(f"• {warning}")
        st.button(
            "LAUNCH SCOREBOARD",
            use_container_width=True,
            disabled=True,
            key="activate_uploaded_edition_disabled",
        )
        st.stop()

    title, host, _palette, participants, _country_info, _votes, voting_countries, *_ = package
    st.markdown(
        f"""
        <div class="alc-ready-card">
            <strong>EDITION READY</strong><br>
            {escape_html_text(title)} — {escape_html_text(host)}<br>
            {len(participants)} participant(s) · {len(voting_countries)} voter(s)
        </div>
        """,
        unsafe_allow_html=True,
    )

    if setup_warnings:
        st.warning(f"{len(setup_warnings)} warning(s) found. The scoreboard can still run.")
        with st.expander("VIEW WARNINGS", expanded=False):
            for warning in setup_warnings:
                st.write(f"• {warning}")

    if st.button(
        "LAUNCH SCOREBOARD",
        type="primary",
        use_container_width=True,
        key="activate_uploaded_edition",
    ):
        activate_uploaded_edition(paths)
        st.rerun()

    st.stop()


if not st.session_state.get("edition_loaded", False):
    render_upload_setup()

_ACTIVE_UPLOADS = active_upload_paths()
VOTES_FILE = _ACTIVE_UPLOADS.get("votes", "")
ELEMENTS_FILE = _ACTIVE_UPLOADS.get("elements", "")
BACKGROUND_IMAGE = _ACTIVE_UPLOADS.get("background", "")
LOGO_FILE = _ACTIVE_UPLOADS.get("logo", "")
BACKSOUND_FILE = _ACTIVE_UPLOADS.get("backsound", "")

# Keep this alias for existing export/cache helpers whose input is the Votes workbook.
EXCEL_FILE = VOTES_FILE

if not VOTES_FILE or not ELEMENTS_FILE or not Path(VOTES_FILE).exists() or not Path(ELEMENTS_FILE).exists():
    st.error("The active uploaded edition is no longer available on the server.")
    st.button(
        "RETURN TO UPLOAD SETUP",
        use_container_width=True,
        on_click=reset_uploaded_edition,
        key="return_to_upload_setup_missing_files",
    )
    st.stop()

_votes_mtime_ns, _votes_size_bytes = file_signature(VOTES_FILE)
_elements_mtime_ns, _elements_size_bytes = file_signature(ELEMENTS_FILE)
_excel_mtime_ns = _votes_mtime_ns

_REQUIRED_SHEET_ERRORS = validate_required_sheets_cached(
    VOTES_FILE,
    _votes_mtime_ns,
    _votes_size_bytes,
    ELEMENTS_FILE,
    _elements_mtime_ns,
    _elements_size_bytes,
    FLAG_LOADER_VERSION,
)
if _REQUIRED_SHEET_ERRORS:
    st.error("Uploaded workbook structure check failed.")
    for _error in _REQUIRED_SHEET_ERRORS:
        st.write(f"• {_error}")
    st.button(
        "RETURN TO UPLOAD SETUP",
        use_container_width=True,
        on_click=reset_uploaded_edition,
        key="return_to_upload_setup_structure_error",
    )
    st.stop()

try:
    (
        TITLE,
        HOST,
        PALETTE,
        participants_df,
        country_info,
        votes_df,
        voting_countries,
        point_to_row,
        voter_col_by_country,
    ) = load_workbook_static_data_cached(
        VOTES_FILE,
        _votes_mtime_ns,
        _votes_size_bytes,
        ELEMENTS_FILE,
        _elements_mtime_ns,
        _elements_size_bytes,
        FLAG_LOADER_VERSION,
    )
except WorkbookLoadError as exc:
    st.error(f"Uploaded edition could not be loaded: {exc}")
    st.button(
        "RETURN TO UPLOAD SETUP",
        use_container_width=True,
        on_click=reset_uploaded_edition,
        key="return_to_upload_setup_load_error",
    )
    st.stop()

TITLE_HTML = escape_html_text(TITLE)
HOST_HTML = escape_html_text(HOST)
PALETTE_CSS_VARS = build_palette_css_variables(PALETTE)


@st.cache_data(show_spinner=False)
def media_to_data_uri_cached(media_file, file_mtime_ns, file_size_bytes):
    """Encode one uploaded local media file until it changes."""
    return image_to_data_uri(media_file) if media_file else ""


_background_mtime_ns, _background_size_bytes = file_signature(BACKGROUND_IMAGE)
BACKGROUND_URI = media_to_data_uri_cached(
    BACKGROUND_IMAGE,
    _background_mtime_ns,
    _background_size_bytes,
)

_backsound_mtime_ns, _backsound_size_bytes = file_signature(BACKSOUND_FILE)
BACKSOUND_URI = media_to_data_uri_cached(
    BACKSOUND_FILE,
    _backsound_mtime_ns,
    _backsound_size_bytes,
)

_logo_mtime_ns, _logo_size_bytes = file_signature(LOGO_FILE)
LOGO_URI = media_to_data_uri_cached(
    LOGO_FILE,
    _logo_mtime_ns,
    _logo_size_bytes,
)

if BACKGROUND_URI:
    APP_BACKGROUND_CSS = (
        "background: "
        f"linear-gradient({hex_to_rgba(PALETTE['PAGE_OVERLAY'], 0.10)}, "
        f"{hex_to_rgba(PALETTE['PAGE_OVERLAY'], 0.10)}), "
        f"url('{BACKGROUND_URI}') center center / cover no-repeat fixed !important;"
    )
else:
    APP_BACKGROUND_CSS = f"background: {PALETTE['PAGE_OVERLAY']} !important;"

_ELEMENT_QC_ERRORS, _ELEMENT_QC_WARNINGS = validate_elements_data(TITLE, HOST)
WORKBOOK_QC_ERRORS, WORKBOOK_QC_WARNINGS = validate_workbook_data(
    participants=participants_df,
    country_info=country_info,
    votes=votes_df,
    voting_countries=voting_countries,
    point_to_row=point_to_row,
    voter_col_by_country=voter_col_by_country,
    background_file=BACKGROUND_IMAGE,
    logo_file=LOGO_FILE,
    backsound_file=BACKSOUND_FILE,
    base_dir=Path(VOTES_FILE).parent,
)
WORKBOOK_QC_ERRORS = _deduplicate_messages(_ELEMENT_QC_ERRORS + WORKBOOK_QC_ERRORS)
WORKBOOK_QC_WARNINGS = _deduplicate_messages(_ELEMENT_QC_WARNINGS + WORKBOOK_QC_WARNINGS)

STARTUP_DIAGNOSTIC_ERRORS, _STARTUP_DIAGNOSTIC_WARNINGS = run_startup_diagnostics(
    base_dir=BASE_DIR,
    votes_file=VOTES_FILE,
    elements_file=ELEMENTS_FILE,
    participant_count=len(participants_df),
    voter_count=len(voting_countries),
    geometry=GEOMETRY,
    animation=ANIMATION,
    points_order=POINTS_ORDER,
    reveal_groups=REVEAL_GROUPS,
    background_file=BACKGROUND_IMAGE,
    logo_file=LOGO_FILE,
    backsound_file=BACKSOUND_FILE,
)

if STARTUP_DIAGNOSTIC_ERRORS:
    st.error(
        f"STARTUP CHECK FAILED — {len(STARTUP_DIAGNOSTIC_ERRORS)} "
        "problem(s) must be fixed."
    )
    for _diagnostic_error in STARTUP_DIAGNOSTIC_ERRORS:
        st.write(f"• {_diagnostic_error}")
    st.button(
        "RETURN TO UPLOAD SETUP",
        use_container_width=True,
        on_click=reset_uploaded_edition,
        key="return_to_upload_setup_startup_error",
    )
    st.stop()

WORKBOOK_QC_PASSED = not WORKBOOK_QC_ERRORS
countries = participants_df["Country"].tolist()


# =============================================================================
# 6. SESSION STATE INITIALIZATION AND INTERACTION CALLBACKS
# =============================================================================

initialize_session_state()


# Opening mode is kept for the current Streamlit session.
# A fresh session starts from the mode-selection screen again.
if "app_mode" not in st.session_state:
    st.session_state.app_mode = None
if "rehearsal_no_animation" not in st.session_state:
    st.session_state.rehearsal_no_animation = False
if "rehearsal_vote_selector" not in st.session_state:
    st.session_state.rehearsal_vote_selector = int(st.session_state.get("voter_idx", 0) or 0)
if "rehearsal_checkpoint" not in st.session_state:
    st.session_state.rehearsal_checkpoint = None


def select_app_mode(mode):
    """Open a clean Production run or restore the Rehearsal checkpoint."""
    if mode == "rehearsal":
        restore_rehearsal_checkpoint()
    else:
        reset_production_progress()
        st.session_state.rehearsal_no_animation = False

    st.session_state.app_mode = mode
    st.session_state.entered_voting_arena = False
    st.session_state.show_final_standing = False
    st.session_state.landing_entry_animation = True
    st.session_state.page_entry_animation_nonce += 1
    st.session_state.rehearsal_vote_selector = int(
        st.session_state.get("voter_idx", 0) or 0
    )


def clear_rehearsal_animation_state():
    """Remove any pending visual animation without changing awarded points."""
    st.session_state.fly_entries = []
    st.session_state.animation_snapshot = None
    st.session_state.animation_locked_until = 0.0


def reveal_next_without_animation():
    """Run the normal reveal sequence but apply points immediately."""
    clear_rehearsal_animation_state()

    if not st.session_state.hod_revealed:
        st.session_state.hod_revealed = True
        return

    if st.session_state.group_idx >= len(REVEAL_GROUPS):
        if st.session_state.voter_idx >= len(voting_countries) - 1:
            st.session_state.show_final_standing = True
        else:
            st.session_state.voter_idx += 1
            st.session_state.point_idx = 0
            st.session_state.group_idx = 0
            st.session_state.hod_revealed = False
            st.session_state.rehearsal_vote_selector = st.session_state.voter_idx
        return

    current_group = REVEAL_GROUPS[st.session_state.group_idx]
    current_voter_country = current_voter(voting_countries)

    for points in current_group:
        recipient = vote_recipient(
            st.session_state.voter_idx,
            points,
            voting_countries,
            point_to_row,
            voter_col_by_country,
            votes_df,
            clean_text,
        )
        if not recipient:
            continue

        st.session_state.totals[recipient] += int(points)
        st.session_state.revealed_log.append({
            "Voter": current_voter_country,
            "Recipient": recipient,
            "Points": int(points),
        })

    st.session_state.group_idx += 1
    st.session_state.point_idx += len(current_group)
    st.session_state.animation_nonce += 1


def toggle_rehearsal_animation_callback():
    """Switch between normal live animation and instant rehearsal reveals."""
    if st.session_state.get("app_mode") != "rehearsal":
        return
    st.session_state.rehearsal_no_animation = not bool(
        st.session_state.get("rehearsal_no_animation", False)
    )
    clear_rehearsal_animation_state()


def go_to_rehearsal_vote(target_idx):
    """Rebuild standings through the voter immediately before target_idx."""
    if st.session_state.get("app_mode") != "rehearsal" or not voting_countries:
        return

    target_idx = max(0, min(int(target_idx), len(voting_countries) - 1))
    rebuilt_totals = defaultdict(int)
    rebuilt_log = []

    # Complete every voter before the selected one using the workbook source.
    for voter_idx in range(target_idx):
        voter_country = voting_countries[voter_idx]
        for points in POINTS_ORDER:
            recipient = vote_recipient(
                voter_idx,
                points,
                voting_countries,
                point_to_row,
                voter_col_by_country,
                votes_df,
                clean_text,
            )
            if not recipient:
                continue

            rebuilt_totals[recipient] += int(points)
            rebuilt_log.append({
                "Voter": voter_country,
                "Recipient": recipient,
                "Points": int(points),
            })

    # Keep every participant initialized, including countries still on zero.
    for country in countries:
        rebuilt_totals[country] += 0

    st.session_state.totals = rebuilt_totals
    st.session_state.revealed_log = rebuilt_log
    st.session_state.voter_idx = target_idx
    st.session_state.point_idx = 0
    st.session_state.group_idx = 0
    st.session_state.hod_revealed = False
    st.session_state.show_final_standing = False
    st.session_state.rehearsal_vote_selector = target_idx
    st.session_state.animation_nonce += 1
    clear_rehearsal_animation_state()


def go_to_selected_vote_callback():
    target_idx = st.session_state.get(
        "rehearsal_vote_selector",
        st.session_state.get("voter_idx", 0),
    )
    go_to_rehearsal_vote(target_idx)


def reveal_next_callback():
    if (
        st.session_state.get("app_mode") == "rehearsal"
        and st.session_state.get("rehearsal_no_animation", False)
    ):
        reveal_next_without_animation()
        return

    reveal_next(
        voting_countries=voting_countries,
        countries=countries,
        country_info=country_info,
        points_order=POINTS_ORDER,
        reveal_groups=REVEAL_GROUPS,
        animation_cfg=ANIMATION,
        point_to_row=point_to_row,
        voter_col_by_country=voter_col_by_country,
        votes_df=votes_df,
        clean_text_func=clean_text,
        build_ranking_dataframe_fn=build_ranking_dataframe,
    )


def undo_last_callback():
    # Handle Undo HoD directly in the main script. This check must happen
    # before looking at revealed_log, whose latest entry can still belong to
    # the previous voter when the current voter has not revealed any points.
    if (
        not animation_is_active()
        and st.session_state.get("hod_revealed", False)
        and int(st.session_state.get("group_idx", 0) or 0) == 0
    ):
        st.session_state.hod_revealed = False
        st.session_state.fly_entries = []
        st.session_state.animation_snapshot = None
        st.session_state.animation_locked_until = 0.0
        return

    undo_last(voting_countries, REVEAL_GROUPS)


# =============================================================================
# 7. EXPORT AND FINAL-RESULT DATA BUILDERS
# =============================================================================

def build_complete_vote_data():
    return build_complete_vote_data_from_source(
        countries=countries,
        voting_countries=voting_countries,
        voter_col_by_country=voter_col_by_country,
        votes_df=votes_df,
        point_to_row=point_to_row,
        country_info=country_info,
        points_order=POINTS_ORDER,
    )


def build_result_excel_bytes():
    return build_result_excel_bytes_from_source(
        participants_df=participants_df,
        country_info=country_info,
        votes_df=votes_df,
        voting_countries=voting_countries,
        point_to_row=point_to_row,
        voter_col_by_country=voter_col_by_country,
        countries=countries,
        points_order=POINTS_ORDER,
    )


@st.cache_data(show_spinner=False)
def build_result_excel_bytes_cached(excel_file, file_mtime_ns):
    # file_mtime_ns is part of the cache key, so replacing/editing the source
    # workbook automatically rebuilds the downloadable result.
    return build_result_excel_bytes()


RESULT_EXCEL_BYTES = build_result_excel_bytes_cached(EXCEL_FILE, _excel_mtime_ns)
_safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", TITLE).strip("_") or "ALC_76"
RESULT_EXCEL_FILENAME = f"{_safe_title}_Voting_Grid.xlsx"



# =============================================================================
# 8. LIVE RANKING, FINAL RANKING, AND VOTE-BADGE DATA
# =============================================================================

# Build the current ranking after the latest reveal.
ranking_df = build_ranking_dataframe(
        countries=countries,
        country_info=country_info,
        points_order=POINTS_ORDER,
        totals=st.session_state.totals,
        revealed_log=st.session_state.revealed_log,
    )

_rows_per_column = GEOMETRY.rows_per_column
col1_rows = ranking_df.iloc[0:_rows_per_column]
col2_rows = ranking_df.iloc[_rows_per_column:2 * _rows_per_column]
col3_rows = ranking_df.iloc[2 * _rows_per_column:3 * _rows_per_column]
col4_rows = ranking_df.iloc[3 * _rows_per_column:4 * _rows_per_column]

# Complete final ranking, used by the Final Standing screen.
# It reads all votes from the source workbook, so the landing-screen button
# can preview the finished standings before the live reveal. Because this
# result depends only on the workbook, cache it across normal Streamlit reruns.
@st.cache_data(show_spinner=False)
def build_final_standing_dataframe_cached(excel_file, file_mtime_ns):
    # file_mtime_ns is part of the cache key. Saving or replacing the workbook
    # automatically rebuilds the complete vote calculation and final ranking.
    final_totals, final_log, _final_vote_matrix = build_complete_vote_data()
    return build_ranking_dataframe(
        countries=countries,
        country_info=country_info,
        points_order=POINTS_ORDER,
        totals=final_totals,
        revealed_log=final_log,
    )


final_standing_df = build_final_standing_dataframe_cached(
    EXCEL_FILE,
    _excel_mtime_ns,
)
final_col1_rows = final_standing_df.iloc[0:_rows_per_column]
final_col2_rows = final_standing_df.iloc[_rows_per_column:2 * _rows_per_column]
final_col3_rows = final_standing_df.iloc[2 * _rows_per_column:3 * _rows_per_column]
final_col4_rows = final_standing_df.iloc[3 * _rows_per_column:4 * _rows_per_column]


# Snapshot values used repeatedly during this render. These are read only
# after Streamlit has applied the current callback, so they stay consistent
# throughout the rerun without repeated session-state/function lookups.
voter = current_voter(voting_countries)
active_fly_entries = st.session_state.get("fly_entries", []) or []
hod_revealed = bool(st.session_state.get("hod_revealed", False))
current_voter_idx = int(st.session_state.get("voter_idx", 0) or 0)
current_point_idx = int(st.session_state.get("point_idx", 0) or 0)
voter_count = len(voting_countries)
current_app_mode = st.session_state.get("app_mode")
is_rehearsal_mode = current_app_mode == "rehearsal"
rehearsal_no_animation_active = bool(
    st.session_state.get("rehearsal_no_animation", False)
)
entered_voting_arena = bool(
    st.session_state.get("entered_voting_arena", False)
)
show_final_standing = bool(
    st.session_state.get("show_final_standing", False)
)

# Badges for points received from the CURRENT voter only.
# They stay visible during the current voter and reset automatically on Next Voter.
current_vote_badges = {}
for item in st.session_state.revealed_log:
    if item.get("Voter") == voter:
        recipient = item.get("Recipient", "")
        pts = int(item.get("Points", 0) or 0)
        if recipient:
            current_vote_badges[recipient] = pts

# Newly revealed points should appear only after their flying ball lands.
latest_badge_delay_ms = {}
current_fly_points = {}
for i, item in enumerate(active_fly_entries):
    recipient = item.get("Recipient", "")
    pts = int(item.get("Points", 0) or 0)
    if recipient:
        latest_badge_delay_ms[recipient] = int(i * ANIMATION.ball_stagger_ms + ANIMATION.ball_flight_ms - ANIMATION.badge_early_offset_ms)
        current_fly_points[recipient] = current_fly_points.get(recipient, 0) + pts


# =============================================================================
# 9. SCOREBOARD ROW AND HTML DOCUMENT BUILDERS
# =============================================================================

def render_rows(df):
    output = ""
    snapshot = st.session_state.get("animation_snapshot") or {}
    pre_order = snapshot.get("pre_order") or []
    post_order = snapshot.get("post_order") or []
    pre_slot = {country: idx for idx, country in enumerate(pre_order)}
    post_slot = {country: idx for idx, country in enumerate(post_order)}
    row_delay = int(snapshot.get("row_delay_ms", 0) or 0)
    nonce = snapshot.get("nonce", 0)

    for rank, row in df.iterrows():
        country = clean_text(row["Country"])
        country_attr = escape_html_text(country)
        country_label = escape_html_text(country.upper())
        old_slot = pre_slot.get(country, int(rank) - 1)
        new_slot = post_slot.get(country, int(rank) - 1)

        old_col, old_row = divmod(old_slot, GEOMETRY.rows_per_column)
        new_col, new_row = divmod(new_slot, GEOMETRY.rows_per_column)
        dx_cols = old_col - new_col
        dy_px = (old_row - new_row) * GEOMETRY.row_step_px

        # IMPORTANT: the rank number is NOT animated.
        # Only this inner country pad moves, so slots 01-40 stay locked.
        anim_class = " pad-animate" if pre_order and (old_slot != new_slot) else ""
        style = (
            f"--move-x: calc({dx_cols} * (100% + {GEOMETRY.column_translation_extra_px}px)); "
            f"--move-y: {dy_px}px; "
            f"--row-delay: {row_delay}ms; "
            f"--row-slide: {ANIMATION.row_slide_ms}ms;"
        )

        badge_points = current_vote_badges.get(country)
        badge_html = ""
        if badge_points:
            delay = latest_badge_delay_ms.get(country, 0)
            if delay > 0:
                badge_html = f'<div class="vote-gain-badge vote-gain-new" style="--badge-delay:{delay}ms;">+{badge_points}</div>'
            else:
                badge_html = f'<div class="vote-gain-badge">+{badge_points}</div>'

        final_points = int(row["Points"])
        flying_added = int(current_fly_points.get(country, 0) or 0)
        display_points = final_points - flying_added if flying_added else final_points
        points_delay = latest_badge_delay_ms.get(country, 0)
        points_extra_class = " points-waiting" if flying_added else ""

        output += f"""
        <div class="score-row" data-nonce="{nonce}">
            <div class="rank-pill">{rank:02d}</div>
            <div class="moving-pad{anim_class}" data-country="{country_attr}" style="{style}">
                <div class="flag-circle">{flag_html(row["Flag"], GEOMETRY.flag_width_px, GEOMETRY.flag_height_px, True, row.get("FallbackFlag", ""))}</div>
                <div class="country-bar">
                    <div class="country-name">{country_label}</div>
                </div>
                {badge_html}
                <div class="points-box{points_extra_class}" data-final-points="{final_points}" data-display-points="{display_points}" data-points-delay="{points_delay}">{display_points}</div>
            </div>
        </div>
        """

    return output


def render_final_rows(df):
    """Render static ranking pads for the full-width Final Standing screen."""
    output = ""
    for rank, row in df.iterrows():
        country = clean_text(row["Country"])
        points = int(row["Points"])
        safe_country = escape_html_text(country)
        country_label = escape_html_text(country.upper())
        output += f"""
        <div class="score-row">
            <div class="rank-pill">{rank:02d}</div>
            <div class="moving-pad" data-country="{safe_country}">
                <div class="flag-circle">{flag_html(row["Flag"], GEOMETRY.flag_width_px, GEOMETRY.flag_height_px, True, row.get("FallbackFlag", ""))}</div>
                <div class="country-bar">
                    <div class="country-name">{country_label}</div>
                </div>
                <div class="points-box">{points}</div>
            </div>
        </div>
        """
    return output


voter_flag = country_info.get(voter, {}).get("Flag", "")
voter_flag_fallback = country_info.get(voter, {}).get("FallbackFlag", "")
voter_hod = country_info.get(voter, {}).get("HoD", "")


remaining_points = POINTS_ORDER[current_point_idx:]
point_pad_html = ""

# When a reveal group is flying, do NOT blank all of its point bubbles at once.
# Keep each original bubble visible in the point pad, then hide it only when
# that specific ball starts flying. This prevents the lower-score row from
# disappearing immediately after clicking Reveal Lower Scores.
launching_point_delay = {}
for i, item in enumerate(active_fly_entries):
    try:
        launching_point_delay[int(item.get("Points", 0))] = ANIMATION.ball_launch_delay_ms + (i * ANIMATION.ball_stagger_ms)
    except Exception:
        pass

for point_value in POINTS_ORDER:
    if not hod_revealed:
        point_pad_html += f'<div class="point-bubble pre" data-point="{point_value}">{point_value}</div>'
    elif point_value in launching_point_delay:
        delay = launching_point_delay[point_value]
        point_pad_html += f'<div class="point-bubble launching" data-point="{point_value}" style="--launch-delay:{delay}ms;">{point_value}</div>'
    elif point_value in remaining_points:
        point_pad_html += f'<div class="point-bubble" data-point="{point_value}">{point_value}</div>'
    else:
        point_pad_html += f'<div class="point-bubble empty" data-point="{point_value}"><span style="opacity:0">{point_value}</span></div>'

    # Keep the vote bubbles balanced: 1-7 on the first row,
    # then 8, 10, 12, 14, 17, 20 on the second row.
    if point_value == POINTS_ORDER[GEOMETRY.point_first_row_count - 1]:
        point_pad_html += '<div class="point-break"></div>'


hod_display = (
    f'<span class="hod-name">{escape_html_text(voter_hod)}</span>'
    if hod_revealed
    else '<span class="hod-placeholder">&nbsp;</span>'
)

# Flying balls are rendered by the parent-page JavaScript overlay,
# so no separate iframe fly-ball HTML is needed here.

SCOREBOARD_CSS = load_text_asset("styles/scoreboard.css") + build_scoreboard_geometry_css()
_SCOREBOARD_COLUMNS_HTML = f"""
            <div>{render_rows(col1_rows)}</div>
            <div>{render_rows(col2_rows)}</div>
            <div>{render_rows(col3_rows)}</div>
            <div>{render_rows(col4_rows)}</div>
"""

# Fallback document for Streamlit versions that do not provide st.html.
scoreboard_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
{SCOREBOARD_CSS.replace("__PALETTE_CSS_VARS__", PALETTE_CSS_VARS)}
</style>
</head>
<body>
    <div class="wrapper">
        <div class="score-grid">
{_SCOREBOARD_COLUMNS_HTML}
        </div>
    </div>
</body>
</html>
"""

# Preferred live renderer: direct DOM, no large iframe reload on every rerun.
NATIVE_SCOREBOARD_CSS = scope_scoreboard_css_for_native(SCOREBOARD_CSS)
scoreboard_native_html = f"""
<style>
{NATIVE_SCOREBOARD_CSS}
</style>
<div id="alc-scoreboard-root">
    <div class="wrapper">
        <div class="score-grid">
{_SCOREBOARD_COLUMNS_HTML}
        </div>
    </div>
</div>
"""


# Reuse the exact country-pad styling, but remove the voting panel and render
# all 40 final placements across the full page.
_final_head = scoreboard_html.split("<body>", 1)[0]
FINAL_STANDING_CSS = load_text_asset("styles/final_standing.css")
_final_head = _final_head.replace("</head>", f"<style>\n{FINAL_STANDING_CSS}\n</style></head>")
final_standing_html = f"""{_final_head}<body>
    <div class="wrapper final-wrapper">
        <div class="score-grid final-score-grid">
            <div>{render_final_rows(final_col1_rows)}</div>
            <div>{render_final_rows(final_col2_rows)}</div>
            <div>{render_final_rows(final_col3_rows)}</div>
            <div>{render_final_rows(final_col4_rows)}</div>
        </div>
    </div>
</body>
</html>
"""

# Native Final Standing rendering keeps every ranking row in the main page DOM.
# This is required for a clean browser-side JPG capture without iframe gaps.
NATIVE_FINAL_STANDING_CSS = scope_scoreboard_css_for_native(
    SCOREBOARD_CSS + "\n" + FINAL_STANDING_CSS,
    root_selector="#alc-final-standing-root",
)
final_standing_native_html = f"""
<style>
{NATIVE_FINAL_STANDING_CSS}
</style>
<div id="alc-final-standing-root">
    <div class="wrapper final-wrapper">
        <div class="score-grid final-score-grid">
            <div>{render_final_rows(final_col1_rows)}</div>
            <div>{render_final_rows(final_col2_rows)}</div>
            <div>{render_final_rows(final_col3_rows)}</div>
            <div>{render_final_rows(final_col4_rows)}</div>
        </div>
    </div>
</div>
"""


progress_pct = 0
if voter_count:
    progress_pct = int(((current_voter_idx + 1) / voter_count) * 100)


# =============================================================================
# 10. PAGE-ENTRY STATE AND APPLICATION CSS
# =============================================================================

# Page-entry fade is injected into the main stylesheet so it never creates
# a temporary Streamlit block that changes vertical layout on the next rerun.
# The keyframe name includes a nonce, forcing the existing block-container DOM
# element to replay the animation when entering Arena or Final Standing.
PAGE_ENTRY_CSS = ""
_page_entry_nonce = int(st.session_state.get("page_entry_animation_nonce", 0))
_page_entry_keyframe = f"alc-page-enter-{_page_entry_nonce}"

if not entered_voting_arena:
    if st.session_state.get("landing_entry_animation", False):
        PAGE_ENTRY_CSS = f"""
        @keyframes {_page_entry_keyframe} {{
            0% {{ opacity: 0; }}
            100% {{ opacity: 1; }}
        }}
        .block-container {{
            opacity: 0;
            transform: none !important;
            animation: {_page_entry_keyframe} 320ms ease-out 180ms forwards !important;
            will-change: opacity;
        }}
        """
        st.session_state.landing_entry_animation = False
elif st.session_state.get("arena_entry_animation", False):
    PAGE_ENTRY_CSS = f"""
    @keyframes {_page_entry_keyframe} {{
        0% {{ opacity: 0; }}
        100% {{ opacity: 1; }}
    }}
    .block-container {{
        opacity: 0;
        transform: none !important;
        animation: {_page_entry_keyframe} 320ms ease-out 220ms forwards !important;
        will-change: opacity;
    }}
    """
    st.session_state.arena_entry_animation = False


# PAGE CSS FOR STREAMLIT
HOD_PENDING_CSS = """
/* Before Reveal HoD, use the same silver/grey visual language as the
   inactive point bubbles. Removing the pending class restores the normal
   gold palette immediately after the HoD is revealed. */
.hod-card.hod-card-pending {
    opacity: 0.82;
    background: radial-gradient(
        circle at 35% 30%,
        rgba(255,255,255,0.88) 0%,
        rgba(210,210,210,0.68) 48%,
        rgba(50,50,50,0.58) 100%
    ) !important;
    border-color: rgba(255,255,255,0.20) !important;
    box-shadow:
        inset 0 1px 3px rgba(255,255,255,0.18),
        0 2px 8px rgba(0,0,0,0.28) !important;
}

.hod-card.hod-card-pending .hod-label-left {
    color: rgba(0,0,0,0.82) !important;
    text-shadow: none !important;
}
"""

APP_CSS = (
    load_text_asset("styles/app.css")
    .replace("__APP_BACKGROUND_CSS__", APP_BACKGROUND_CSS)
    .replace("__PALETTE_CSS_VARS__", PALETTE_CSS_VARS)
    .replace("__POINT_BUBBLE_HIDE_MS__", str(ANIMATION.point_bubble_hide_ms))
    .replace("__PAGE_ENTRY_CSS__", PAGE_ENTRY_CSS)
    + build_point_pad_geometry_css()
    + HOD_PENDING_CSS
)
st.markdown(f"<style>\n{APP_CSS}\n</style>", unsafe_allow_html=True)


# =============================================================================
# 11. PAGE RENDERERS
# =============================================================================

def render_home_button():
    """Render HOME at the upper-right without fixed/absolute positioning."""
    _, home_col = st.columns([8.7, 1.3], gap="small")
    with home_col:
        with st.container(key="alc_landing_home"):
            st.button(
                "HOME",
                key="alc_home_button",
                use_container_width=True,
                on_click=go_home,
            )


def render_scoreboard_header(
    *,
    title_html,
    host_html,
    logo_uri="",
    rehearsal=False,
    rehearsal_no_animation=False,
    voter_count=0,
    voting_countries=None,
    toggle_animation_callback=None,
    go_to_vote_callback=None,
    show_final_download=False,
    final_download_callback=None,
):
    """Render logo, title, and controls in one stable three-column header row."""
    voting_countries = voting_countries or []
    # Equal side columns keep the complete title box centered on the viewport.
    logo_col, title_col, controls_col = st.columns([1.225, 7.55, 1.225], gap="small")

    with logo_col:
        if logo_uri:
            st.markdown(
                f'<div class="alc-logo-column"><img src="{logo_uri}" alt="ALC logo"></div>',
                unsafe_allow_html=True,
            )

    with title_col:
        st.markdown(
            f"""
            <div class="alc-header-grid-title">
                <div class="title-shell">
                    <div class="main-title">{title_html}</div>
                    <div class="title-divider"></div>
                    <div class="host-row">{host_html}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with controls_col:
        with st.container(key="alc_header_controls"):
            st.button(
                "HOME",
                key="alc_home_button",
                use_container_width=True,
                on_click=go_home,
            )

            if show_final_download:
                st.button(
                    "DOWNLOAD",
                    key="download_final_standing_jpg",
                    use_container_width=True,
                    on_click=final_download_callback,
                )

            if rehearsal:
                animation_button_label = (
                    "ANIMATION: OFF"
                    if rehearsal_no_animation
                    else "ANIMATION: ON"
                )
                st.button(
                    animation_button_label,
                    key="rehearsal_animation_toggle",
                    use_container_width=True,
                    on_click=toggle_animation_callback,
                )
                st.selectbox(
                    "GO TO",
                    options=list(range(voter_count)),
                    format_func=lambda idx: (
                        f"Vote {idx + 1:02d} — {voting_countries[idx]}"
                    ),
                    key="rehearsal_vote_selector",
                    on_change=go_to_vote_callback,
                    label_visibility="collapsed",
                )


def render_mode_selector():
    """First screen shown when the app opens."""
    render_bgm_controller("reset", BACKSOUND_URI, clean_text)
    st.markdown(
        f"""
        <div class="welcome-screen">
            <div class="welcome-kicker">SELECT MODE</div>
            <div class="welcome-title">{TITLE_HTML}</div>
            <div class="welcome-host">CHOOSE HOW TO OPEN THE SCOREBOARD</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.button(
        "PRODUCTION MODE",
        key="select_production_mode",
        use_container_width=True,
        on_click=select_app_mode,
        args=("production",),
    )
    st.button(
        "REHEARSAL MODE",
        key="select_rehearsal_mode",
        use_container_width=True,
        on_click=select_app_mode,
        args=("rehearsal",),
    )
    st.button(
        "CHANGE UPLOADED EDITION",
        key="change_uploaded_edition_mode_selector",
        use_container_width=True,
        on_click=reset_uploaded_edition,
    )
    st.stop()


def render_production_landing():
    """Live welcome screen: only the voting-arena action is available."""
    render_home_button()
    render_bgm_controller("reset", BACKSOUND_URI, clean_text)
    st.markdown(
        f"""
        <div class="welcome-screen mode-landing-screen">
            <div class="welcome-kicker">WELCOME TO</div>
            <div class="welcome-title">{TITLE_HTML}</div>
            <div class="welcome-host">{HOST_HTML}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Keep the same workbook safety checks as the original landing page.
    if WORKBOOK_QC_ERRORS:
        st.error(
            f"WORKBOOK QC FAILED — {len(WORKBOOK_QC_ERRORS)} error(s) must be fixed "
            "before entering the voting arena."
        )
    elif WORKBOOK_QC_WARNINGS:
        st.warning(
            f"WORKBOOK QC WARNING — {len(WORKBOOK_QC_WARNINGS)} item(s) need attention. "
            "The voting arena can still be opened."
        )

    if WORKBOOK_QC_ERRORS or WORKBOOK_QC_WARNINGS:
        with st.expander(
            "VIEW WORKBOOK QC REPORT",
            expanded=bool(WORKBOOK_QC_ERRORS),
        ):
            if WORKBOOK_QC_ERRORS:
                st.markdown("**Errors — arena entry is blocked**")
                for qc_error in WORKBOOK_QC_ERRORS:
                    st.write(f"• {qc_error}")

            if WORKBOOK_QC_WARNINGS:
                st.markdown("**Warnings — the scoreboard can still run**")
                for qc_warning in WORKBOOK_QC_WARNINGS:
                    st.write(f"• {qc_warning}")

    st.button(
        "ENTER VOTING ARENA",
        key="enter_voting_arena_production",
        use_container_width=True,
        on_click=enter_voting_arena,
        disabled=not WORKBOOK_QC_PASSED,
    )
    st.stop()


def render_rehearsal_landing():
    """Rehearsal welcome screen without any edition-change action."""
    render_home_button()
    render_bgm_controller("reset", BACKSOUND_URI, clean_text)
    st.markdown(
        f"""
        <div class="welcome-screen mode-landing-screen">
            <div class="welcome-kicker">WELCOME TO</div>
            <div class="welcome-title">{TITLE_HTML}</div>
            <div class="welcome-host">{HOST_HTML}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if WORKBOOK_QC_ERRORS:
        st.error(
            f"WORKBOOK QC FAILED — {len(WORKBOOK_QC_ERRORS)} error(s) must be fixed "
            "before entering the voting arena."
        )
    elif WORKBOOK_QC_WARNINGS:
        st.warning(
            f"WORKBOOK QC WARNING — {len(WORKBOOK_QC_WARNINGS)} item(s) need attention. "
            "The voting arena can still be opened."
        )

    if WORKBOOK_QC_ERRORS or WORKBOOK_QC_WARNINGS:
        with st.expander("VIEW WORKBOOK QC REPORT", expanded=bool(WORKBOOK_QC_ERRORS)):
            if WORKBOOK_QC_ERRORS:
                st.markdown("**Errors — arena entry is blocked**")
                for qc_error in WORKBOOK_QC_ERRORS:
                    st.write(f"• {qc_error}")
            if WORKBOOK_QC_WARNINGS:
                st.markdown("**Warnings — the scoreboard can still run**")
                for qc_warning in WORKBOOK_QC_WARNINGS:
                    st.write(f"• {qc_warning}")

    st.button(
        "ENTER VOTING ARENA",
        key="enter_voting_arena",
        use_container_width=True,
        on_click=enter_voting_arena,
        disabled=not WORKBOOK_QC_PASSED,
    )
    st.button(
        "VIEW FINAL STANDING",
        key="view_final_standing_start",
        use_container_width=True,
        on_click=open_final_standing,
        disabled=not WORKBOOK_QC_PASSED,
    )
    st.download_button(
        "DOWNLOAD RESULT",
        data=RESULT_EXCEL_BYTES,
        file_name=RESULT_EXCEL_FILENAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_result_landing",
        use_container_width=True,
        disabled=not WORKBOOK_QC_PASSED,
    )
    st.stop()


def render_voting_arena(ctx):
    """Render the arena locally so Rehearsal Controls need no second file."""
    TITLE = ctx["TITLE"]
    HOST = ctx["HOST"]
    scoreboard_html = ctx["scoreboard_html"]
    scoreboard_native_html = ctx["scoreboard_native_html"]
    flag_html = ctx["flag_html"]
    voter_flag = ctx["voter_flag"]
    voter = ctx["voter"]
    hod_display = ctx["hod_display"]
    progress_pct = ctx["progress_pct"]
    voting_countries = ctx["voting_countries"]
    point_pad_html = ctx["point_pad_html"]
    animation_is_active_fn = ctx["animation_is_active"]
    reveal_next_callback_fn = ctx["reveal_next_callback"]
    undo_last_callback_fn = ctx["undo_last_callback"]
    animation_cfg = ctx["ANIMATION"]
    pending_animation_duration_ms_fn = ctx["pending_animation_duration_ms"]
    clean_text_fn = ctx["clean_text"]
    backsound_uri = ctx["BACKSOUND_URI"]
    render_bgm_controller_fn = ctx["render_bgm_controller"]
    is_rehearsal = bool(ctx.get("is_rehearsal", False))
    rehearsal_no_animation = bool(ctx.get("rehearsal_no_animation", False))
    toggle_animation_callback = ctx.get("toggle_rehearsal_animation_callback")
    go_to_vote_callback = ctx.get("go_to_selected_vote_callback")

    session_state = st.session_state
    hod_revealed = bool(session_state.get("hod_revealed", False))
    group_idx = int(session_state.get("group_idx", 0) or 0)
    voter_idx = int(session_state.get("voter_idx", 0) or 0)
    voter_count = len(voting_countries)
    fly_entries_for_js = session_state.get("fly_entries", []) or []

    title_html = html.escape(clean_text_fn(TITLE), quote=True)
    host_html = html.escape(clean_text_fn(HOST), quote=True)
    voter_html = html.escape(clean_text_fn(voter).upper(), quote=True)
    logo_uri = ctx.get("LOGO_URI", "")
    hod_card_class = (
        "hod-card"
        if hod_revealed
        else "hod-card hod-card-pending"
    )

    def load_arena_script(filename):
        # Reuse the same metadata-aware cache used by the CSS assets.
        return load_text_asset(f"scripts/{filename}")

    render_bgm_controller_fn("start", backsound_uri, clean_text_fn)

    render_scoreboard_header(
        title_html=title_html,
        host_html=host_html,
        logo_uri=logo_uri,
        rehearsal=is_rehearsal,
        rehearsal_no_animation=rehearsal_no_animation,
        voter_count=voter_count,
        voting_countries=voting_countries,
        toggle_animation_callback=toggle_animation_callback,
        go_to_vote_callback=go_to_vote_callback,
    )

    left, right = st.columns([4.05, 1.25], gap="small")

    with left:
        if hasattr(st, "html"):
            # Direct DOM rendering removes the large scoreboard iframe, the
            # main source of full-grid blinking during Streamlit reruns.
            st.html(scoreboard_native_html)
        else:
            # Compatibility fallback for Streamlit versions older than 1.33.
            components.html(scoreboard_html, height=730, scrolling=False)

    with right:
        st.markdown('<div class="now-label">NOW VOTING</div>', unsafe_allow_html=True)
        st.markdown('<div class="right-panel-content-up">', unsafe_allow_html=True)

        st.markdown(
            f"""
            <div class="voter-card">
                <div class="big-flag">
                    {flag_html(voter_flag, 190, 118, False, voter_flag_fallback)}
                </div>
                <div class="voter-name">{voter_html}</div>
            </div>

            <div class="{hod_card_class}">
                <span class="hod-label-left">HoD:</span>
                <span class="hod-name-right">{hod_display}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="status">
                <span style='color:var(--alc-vote-status-label);'>VOTE:</span>
                <span style='color:var(--alc-vote-status-number);'> {voter_idx + 1}/{voter_count}</span>
                <div class="progress-track">
                    <div class="progress-fill" style="width:{progress_pct}%;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="button-section"></div>', unsafe_allow_html=True)
        animation_active = animation_is_active_fn()

        if not hod_revealed:
            next_label = "Reveal HoD"
        elif group_idx == 0:
            next_label = "Reveal Lower Scores"
        elif group_idx == 1:
            next_label = "Reveal 14pts"
        elif group_idx == 2:
            next_label = "Reveal 17pts"
        elif group_idx == 3:
            next_label = "Reveal 20pts"
        elif voter_idx >= voter_count - 1:
            next_label = "Final Standing"
        else:
            next_label = "Next Voter"

        b1, b2 = st.columns([3, 1])
        with b1:
            st.button(
                next_label,
                key="arena_primary_action",
                use_container_width=True,
                on_click=reveal_next_callback_fn,
            )
        with b2:
            st.button(
                "Undo",
                key="arena_undo_action",
                use_container_width=True,
                on_click=undo_last_callback_fn,
            )

        st.markdown(
            f"""
            <div class="point-pad">
                {point_pad_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

        if animation_active:
            unlock_ms = int(
                max(
                    120,
                    (
                        float(session_state.get("animation_locked_until", 0.0) or 0.0)
                        - time.time()
                    )
                    * 1000
                    + 80,
                )
            )
            button_lock_js = load_arena_script("button_lock.js").replace(
                "__UNLOCK_MS__", str(unlock_ms)
            )
            components.html(
                f"<script>\n{button_lock_js}\n</script>",
                height=1,
                scrolling=False,
            )

        if fly_entries_for_js:
            js_entries = json_for_inline_script(fly_entries_for_js)
            js_flight = int(animation_cfg.ball_flight_ms)
            js_stagger = int(animation_cfg.ball_stagger_ms)
            js_cleanup = int(
                pending_animation_duration_ms_fn(
                    len(fly_entries_for_js), animation_cfg
                )
                + animation_cfg.fly_layer_cleanup_buffer_ms
            )
            voting_animation_js = (
                inject_animation_geometry(load_arena_script("voting_animation.js"))
                .replace("__ENTRIES__", js_entries)
                .replace("__FLIGHT_MS__", str(js_flight))
                .replace("__STAGGER_MS__", str(js_stagger))
                .replace("__CLEANUP_MS__", str(js_cleanup))
                .replace(
                    "__LAUNCH_DELAY_MS__",
                    str(int(animation_cfg.ball_launch_delay_ms)),
                )
                .replace(
                    "__BADGE_EARLY_OFFSET_MS__",
                    str(int(animation_cfg.badge_early_offset_ms)),
                )
            )
            components.html(
                f"<script>\n{voting_animation_js}\n</script>",
                height=1,
                scrolling=False,
            )

        st.markdown("</div>", unsafe_allow_html=True)



def render_final_standing_with_logo(
    *,
    title,
    host,
    final_standing_html,
    final_standing_native_html,
    render_bgm,
    backsound_uri,
    clean_text_func,
    logo_uri="",
):
    """Render Final Standing and optionally export the clean view as JPG."""
    safe_title = html.escape(clean_text_func(title), quote=True)
    safe_host = html.escape(clean_text_func(host), quote=True)
    render_bgm("fadeout", backsound_uri, clean_text_func)

    download_requested = bool(
        st.session_state.get("final_jpg_download_requested", False)
    )
    if download_requested:
        st.session_state.final_jpg_download_requested = False

    render_scoreboard_header(
        title_html=safe_title,
        host_html=safe_host,
        logo_uri=logo_uri,
        rehearsal=False,
        show_final_download=True,
        final_download_callback=request_final_jpg_download,
    )

    if hasattr(st, "html"):
        st.html(final_standing_native_html)
    else:
        components.html(final_standing_html, height=690, scrolling=False)

    if download_requested:
        safe_filename = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            clean_text_func(title),
        ).strip("_") or "ALC_Final_Standing"

        capture_js = f"""
<!doctype html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
</head>
<body>
<script>
(async () => {{
    const parentWindow = window.parent;
    const doc = parentWindow.document;
    const target = doc.querySelector('[data-testid="stAppViewContainer"]');
    if (!target) {{
        console.error('Final Standing capture target was not found.');
        return;
    }}

    const isControlNode = (node) => {{
        if (!(node instanceof parentWindow.Element)) return false;

        if (
            node.matches(
                '[data-testid="stHeader"], [data-testid="stToolbar"], ' +
                '[data-testid="stDecoration"], [data-testid="stStatusWidget"], ' +
                '#MainMenu, footer'
            )
        ) return true;

        if (
            node.classList.contains('st-key-alc_header_controls') ||
            node.closest('.st-key-alc_header_controls')
        ) return true;

        if (node.tagName === 'BUTTON') {{
            const label = (node.textContent || '').trim().toUpperCase();
            if (label === 'HOME' || label === 'DOWNLOAD') return true;
        }}

        return false;
    }};

    try {{
        if (!window.htmlToImage) {{
            throw new Error('html-to-image could not be loaded.');
        }}

        if (doc.fonts && doc.fonts.ready) {{
            await doc.fonts.ready;
        }}

        const images = Array.from(target.querySelectorAll('img'));
        await Promise.all(images.map(async (image) => {{
            try {{
                if (!image.complete) {{
                    await new Promise((resolve) => {{
                        image.addEventListener('load', resolve, {{ once: true }});
                        image.addEventListener('error', resolve, {{ once: true }});
                    }});
                }}
                if (image.decode) await image.decode();
            }} catch (_) {{}}
        }}));

        await new Promise(resolve => parentWindow.requestAnimationFrame(
            () => parentWindow.requestAnimationFrame(resolve)
        ));

        const captureWidth = Math.max(
            target.scrollWidth,
            target.clientWidth,
            parentWindow.innerWidth
        );
        const captureHeight = Math.max(
            target.scrollHeight,
            target.clientHeight,
            parentWindow.innerHeight
        );

        const sourceCanvas = await window.htmlToImage.toCanvas(target, {{
            pixelRatio: Math.min(2.5, Math.max(2, parentWindow.devicePixelRatio || 1)),
            cacheBust: true,
            includeQueryParams: true,
            skipAutoScale: false,
            width: captureWidth,
            height: captureHeight,
            canvasWidth: captureWidth,
            canvasHeight: captureHeight,
            filter: (node) => !isControlNode(node),
            style: {{
                margin: '0',
                transform: 'none',
                transformOrigin: 'top left'
            }}
        }});

        // Crop slightly more from the top so the export matches the tighter on-screen framing.
        const requestedTopCrop = Math.round(Math.max(115, Math.min(175, parentWindow.innerHeight * 0.105)));
        const topCrop = Math.max(0, Math.min(requestedTopCrop, sourceCanvas.height - 120));

        let exportCanvas = sourceCanvas;
        if (topCrop > 0) {{
            exportCanvas = doc.createElement('canvas');
            exportCanvas.width = sourceCanvas.width;
            exportCanvas.height = sourceCanvas.height - topCrop;
            const ctx = exportCanvas.getContext('2d', {{ alpha: false }});
            ctx.drawImage(
                sourceCanvas,
                0, topCrop, sourceCanvas.width, sourceCanvas.height - topCrop,
                0, 0, exportCanvas.width, exportCanvas.height
            );
        }}

        const dataUrl = exportCanvas.toDataURL('image/jpeg', 0.98);

        const link = doc.createElement('a');
        link.href = dataUrl;
        link.download = '{safe_filename}_Final_Standing.jpg';
        link.style.display = 'none';
        doc.body.appendChild(link);
        link.click();
        link.remove();
    }} catch (error) {{
        console.error('Final Standing JPG export failed:', error);
        parentWindow.alert(
            'The Final Standing image could not be created. Please wait for all flags to load, then press DOWNLOAD again.'
        );
    }}
}})();
</script>
</body>
</html>
"""
        components.html(capture_js, height=0, scrolling=False)

    st.stop()


# =============================================================================
# 12. PAGE DISPATCH
# =============================================================================
if not entered_voting_arena:
    if current_app_mode not in {"production", "rehearsal"}:
        render_mode_selector()

    if current_app_mode == "production":
        render_production_landing()

    render_rehearsal_landing()

if show_final_standing:
    render_final_standing_with_logo(
        title=TITLE,
        host=HOST,
        final_standing_html=final_standing_html,
        final_standing_native_html=final_standing_native_html,
        render_bgm=render_bgm_controller,
        backsound_uri=BACKSOUND_URI,
        clean_text_func=clean_text,
        logo_uri=LOGO_URI,
    )

render_voting_arena({
    "TITLE": TITLE,
    "HOST": HOST,
    "scoreboard_html": scoreboard_html,
    "scoreboard_native_html": scoreboard_native_html,
    "flag_html": flag_html,
    "voter_flag": voter_flag,
    "voter": voter,
    "hod_display": hod_display,
    "progress_pct": progress_pct,
    "voting_countries": voting_countries,
    "point_pad_html": point_pad_html,
    "animation_is_active": animation_is_active,
    "reveal_next_callback": reveal_next_callback,
    "undo_last_callback": undo_last_callback,
    "ANIMATION": ANIMATION,
    "pending_animation_duration_ms": pending_animation_duration_ms,
    "clean_text": clean_text,
    "BACKSOUND_URI": BACKSOUND_URI,
    "LOGO_URI": LOGO_URI,
    "render_bgm_controller": render_bgm_controller,
    "is_rehearsal": is_rehearsal_mode,
    "rehearsal_no_animation": rehearsal_no_animation_active,
    "toggle_rehearsal_animation_callback": toggle_rehearsal_animation_callback,
    "go_to_selected_vote_callback": go_to_selected_vote_callback,
})
