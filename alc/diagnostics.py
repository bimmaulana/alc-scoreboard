"""Lightweight startup diagnostics for the ALC scoreboard.

The checks in this module are deliberately read-only. They validate files and
configuration before the live arena starts, but never mutate workbook data,
Streamlit state, or animation state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_REQUIRED_UI_ASSETS = (
    "styles/app.css",
    "styles/scoreboard.css",
    "styles/final_standing.css",
    "scripts/button_lock.js",
    "scripts/voting_animation.js",
)


def _deduplicate(messages: Iterable[str]) -> list[str]:
    """Preserve message order while removing duplicates."""
    return list(dict.fromkeys(message for message in messages if message))


def _check_required_assets(
    base_dir: Path,
    required_assets: Sequence[str],
) -> list[str]:
    errors: list[str] = []

    for relative_path in required_assets:
        path = base_dir / relative_path
        if not path.exists():
            errors.append(f"Required UI asset is missing: {relative_path}")
            continue
        if not path.is_file():
            errors.append(f"Required UI asset is not a file: {relative_path}")
            continue

        try:
            if path.stat().st_size <= 0:
                errors.append(f"Required UI asset is empty: {relative_path}")
                continue
            with path.open("r", encoding="utf-8") as handle:
                handle.read(1)
        except UnicodeDecodeError:
            errors.append(f"Required UI asset is not valid UTF-8 text: {relative_path}")
        except OSError as exc:
            errors.append(f"Required UI asset could not be read: {relative_path} ({exc})")

    return errors


def _check_geometry(geometry, participant_count: int) -> list[str]:
    errors: list[str] = []

    positive_integer_fields = (
        "scoreboard_columns",
        "rows_per_column",
        "row_height_px",
        "row_gap_px",
        "rank_column_width_px",
        "flag_track_width_px",
        "points_box_width_px",
        "pad_height_px",
        "flag_width_px",
        "flag_height_px",
        "point_first_row_count",
        "point_bubble_size_px",
        "flying_ball_size_px",
    )
    nonnegative_integer_fields = (
        "wrapper_padding_left_px",
        "wrapper_padding_right_px",
        "grid_gap_px",
        "point_column_gap_px",
        "point_row_gap_px",
    )

    for field_name in positive_integer_fields:
        value = getattr(geometry, field_name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(
                f"GEOMETRY.{field_name} must be a positive integer; got {value!r}."
            )

    for field_name in nonnegative_integer_fields:
        value = getattr(geometry, field_name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(
                f"GEOMETRY.{field_name} must be a non-negative integer; got {value!r}."
            )

    for field_name in (
        "country_landing_x_ratio",
        "country_landing_y_ratio",
        "point_viewport_fallback_x_ratio",
        "point_viewport_fallback_y_ratio",
        "country_viewport_fallback_x_ratio",
        "country_viewport_fallback_y_ratio",
    ):
        value = getattr(geometry, field_name, None)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            errors.append(
                f"GEOMETRY.{field_name} must be between 0 and 1; got {value!r}."
            )

    columns = getattr(geometry, "scoreboard_columns", 0)
    rows = getattr(geometry, "rows_per_column", 0)
    if isinstance(columns, int) and isinstance(rows, int) and columns > 0 and rows > 0:
        capacity = columns * rows
        if participant_count > capacity:
            errors.append(
                f"Scoreboard geometry has {capacity} slots, but the workbook contains "
                f"{participant_count} participants."
            )

    first_row_count = getattr(geometry, "point_first_row_count", 0)
    if isinstance(first_row_count, int) and first_row_count > 0:
        # The caller separately verifies the actual points list length. Here we
        # only guard against a configuration that could never form two rows.
        if first_row_count < 1:
            errors.append("GEOMETRY.point_first_row_count must be at least 1.")

    return errors


def _check_animation(animation) -> list[str]:
    errors: list[str] = []

    strictly_positive_fields = (
        "ball_flight_ms",
        "row_slide_ms",
    )
    nonnegative_fields = (
        "ball_stagger_ms",
        "ball_after_pad_ms",
        "ball_launch_delay_ms",
        "badge_early_offset_ms",
        "button_lock_buffer_ms",
        "point_bubble_hide_ms",
        "fly_layer_cleanup_buffer_ms",
    )

    for field_name in strictly_positive_fields:
        value = getattr(animation, field_name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(
                f"ANIMATION.{field_name} must be a positive integer; got {value!r}."
            )

    for field_name in nonnegative_fields:
        value = getattr(animation, field_name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(
                f"ANIMATION.{field_name} must be a non-negative integer; got {value!r}."
            )

    return errors


def _check_reveal_configuration(
    points_order: Sequence[int],
    reveal_groups: Sequence[Sequence[int]],
    point_first_row_count: int,
) -> list[str]:
    errors: list[str] = []

    if not points_order:
        return ["POINTS_ORDER is empty."]

    if any(not isinstance(point, int) or isinstance(point, bool) or point <= 0 for point in points_order):
        errors.append("POINTS_ORDER must contain positive integers only.")

    if len(set(points_order)) != len(points_order):
        errors.append("POINTS_ORDER contains duplicate point values.")

    flattened_groups = [point for group in reveal_groups for point in group]
    if flattened_groups != list(points_order):
        errors.append(
            "REVEAL_GROUPS must contain every POINTS_ORDER value exactly once "
            "and in the same reveal order."
        )

    if not isinstance(point_first_row_count, int) or not 0 < point_first_row_count < len(points_order):
        errors.append(
            "GEOMETRY.point_first_row_count must split POINTS_ORDER into two non-empty rows."
        )

    return errors


def _check_workbook_path(path_value, label: str) -> list[str]:
    errors: list[str] = []
    path = Path(path_value) if path_value else Path("")

    if not path_value:
        return [f"{label} workbook has not been uploaded."]
    if not path.exists():
        errors.append(f"{label} workbook file was not found: {path}")
    elif not path.is_file():
        errors.append(f"{label} workbook path is not a file: {path}")
    else:
        try:
            if path.stat().st_size <= 0:
                errors.append(f"{label} workbook file is empty: {path.name}")
        except OSError as exc:
            errors.append(f"{label} workbook metadata could not be read: {path} ({exc})")

    return errors


def run_startup_diagnostics(
    *,
    base_dir,
    votes_file,
    elements_file,
    participant_count: int,
    voter_count: int,
    geometry,
    animation,
    points_order: Sequence[int],
    reveal_groups: Sequence[Sequence[int]],
    background_file="",
    backsound_file="",
    logo_file="",
    required_assets: Sequence[str] = DEFAULT_REQUIRED_UI_ASSETS,
) -> tuple[list[str], list[str]]:
    """Return fatal startup errors and non-fatal startup warnings.

    Vote-content checks remain in ``alc.flag_validation``. This function
    focuses on runtime files, display capacity, and animation configuration.
    Uploaded background, logo, and backsound files are optional.
    """
    base_path = Path(base_dir)
    errors: list[str] = []
    warnings: list[str] = []

    errors.extend(_check_workbook_path(votes_file, "Votes"))
    errors.extend(_check_workbook_path(elements_file, "Elements"))

    if participant_count <= 0:
        errors.append("No participants were loaded from the Votes workbook.")
    if voter_count <= 0:
        errors.append("No voting countries were loaded from the Votes workbook.")

    errors.extend(_check_required_assets(base_path, required_assets))
    errors.extend(_check_geometry(geometry, participant_count))
    errors.extend(_check_animation(animation))
    errors.extend(
        _check_reveal_configuration(
            points_order,
            reveal_groups,
            getattr(geometry, "point_first_row_count", 0),
        )
    )

    return _deduplicate(errors), _deduplicate(warnings)
