import re
from pathlib import Path

import pandas as pd

from .config import POINTS_ORDER
from .flag_loader import clean_text, is_web_url


VOTES_REQUIRED_SHEETS = {"Participants", "Votes"}
ELEMENTS_REQUIRED_SHEETS = {"Elements", "Palette"}


def _workbook_sheet_errors(excel_file, required_sheets, label):
    if not excel_file:
        return [f"{label} workbook has not been uploaded."]

    try:
        available_sheets = set(pd.ExcelFile(excel_file).sheet_names)
    except Exception as exc:
        return [f"{label} workbook could not be opened: {exc}"]

    missing = sorted(required_sheets - available_sheets)
    return [f"{label} workbook is missing required sheet: {sheet}" for sheet in missing]


def validate_required_sheets(votes_file, elements_file=None):
    """Validate the two-workbook deployment structure before loading data."""
    if elements_file is None:
        # Compatibility for an accidental old single-workbook call. The error
        # explains the new public-deployment format instead of crashing.
        return [
            "Two workbooks are required: ALC_Votes.xlsx (Participants + Votes) "
            "and ALC_Elements.xlsx (Elements + Palette)."
        ]

    errors = []
    errors.extend(_workbook_sheet_errors(votes_file, VOTES_REQUIRED_SHEETS, "Votes"))
    errors.extend(_workbook_sheet_errors(elements_file, ELEMENTS_REQUIRED_SHEETS, "Elements"))
    return list(dict.fromkeys(errors))


def validate_elements_data(title, host):
    """Validate required text values from the Elements sheet."""
    errors = []
    warnings = []

    title_text = clean_text(title)
    host_text = clean_text(host)

    if not title_text or title_text.lower().startswith("please fill"):
        errors.append("Elements sheet: Title must be filled in.")
    if not host_text or host_text.lower().startswith("please fill"):
        errors.append("Elements sheet: Host City must be filled in.")

    return errors, warnings


def validate_workbook_data(
    participants,
    country_info,
    votes,
    voting_countries,
    point_to_row,
    voter_col_by_country,
    background_file="",
    backsound_file="",
    logo_file="",
    base_dir=".",
):
    """Run non-destructive QC checks on the uploaded edition.

    Errors block activation of the scoreboard. Warnings are informative only.
    Any participant count from 1 to 40 is supported without a warning.
    """
    errors = []
    warnings = []

    participant_names = participants["Country"].astype(str).str.strip().tolist()
    participant_set = set(participant_names)

    duplicate_participants = sorted({
        country for country in participant_names
        if participant_names.count(country) > 1
    })
    for country in duplicate_participants:
        errors.append(f"Duplicate country in Participants: {country}")

    participant_numbers = participants["ParticipantNo"].tolist()
    duplicate_numbers = sorted({
        number for number in participant_numbers
        if participant_numbers.count(number) > 1
    })
    for number in duplicate_numbers:
        errors.append(f"Duplicate participant running number: {number}")

    if not participant_names:
        errors.append("Participants sheet contains no countries.")
    elif len(participant_names) > 40:
        errors.append(
            f"This edition contains {len(participant_names)} participants, "
            "but the scoreboard supports a maximum of 40."
        )

    duplicate_voters = sorted({
        voter for voter in voting_countries
        if voting_countries.count(voter) > 1
    })
    for voter in duplicate_voters:
        errors.append(f"Duplicate voter in Votes sheet: {voter}")

    unknown_voters = sorted(set(voting_countries) - participant_set)
    for voter in unknown_voters:
        errors.append(f"Voter is not listed in Participants: {voter}")

    missing_voters = sorted(participant_set - set(voting_countries))
    for voter in missing_voters:
        warnings.append(f"Participant has no voting column: {voter}")

    missing_point_rows = [points for points in POINTS_ORDER if points not in point_to_row]
    for points in missing_point_rows:
        errors.append(f"Votes sheet is missing the {points}-point row.")

    unexpected_points = sorted(set(point_to_row) - set(POINTS_ORDER), reverse=True)
    if unexpected_points:
        warnings.append(
            "Votes sheet contains unused point row(s): "
            + ", ".join(str(points) for points in unexpected_points)
        )

    for voter in voting_countries:
        column = voter_col_by_country.get(voter)
        if column is None or column >= votes.shape[1]:
            errors.append(f"Voting column could not be read for {voter}.")
            continue

        recipients = []
        for points in POINTS_ORDER:
            row = point_to_row.get(points)
            if row is None or row >= votes.shape[0]:
                continue

            recipient = clean_text(votes.iloc[row, column])
            if not recipient:
                errors.append(f"{voter}: recipient for {points} points is blank.")
                continue

            recipients.append(recipient)

            if recipient not in participant_set:
                errors.append(
                    f"{voter}: recipient '{recipient}' for {points} points "
                    "is not listed in Participants."
                )
            elif recipient == voter:
                errors.append(f"{voter}: gives {points} points to itself.")

        duplicate_recipients = sorted({
            recipient for recipient in recipients
            if recipients.count(recipient) > 1
        })
        for recipient in duplicate_recipients:
            errors.append(f"{voter}: '{recipient}' receives more than one score.")

        if len(recipients) != len(POINTS_ORDER):
            errors.append(
                f"{voter}: has {len(recipients)} completed scores; "
                f"expected {len(POINTS_ORDER)}."
            )

    # Automatic flag QC. Flag Override is intentionally URL-only for the
    # deployed app because the server cannot read a path on the user's device.
    codes = []
    for country in participant_names:
        info = country_info.get(country, {})
        if not clean_text(info.get("HoD", "")):
            warnings.append(f"HoD name is blank for {country}.")

        code = clean_text(info.get("Code", "")).upper()
        override = clean_text(info.get("FlagOverride", ""))
        resolved_flag = clean_text(info.get("Flag", ""))

        if code:
            if not re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]{1,3})?", code):
                errors.append(
                    f"Country code for {country} must use either AA or AA-XXX format: {code}"
                )
            else:
                codes.append(code)
        elif not override:
            errors.append(
                f"Country code is blank for {country}; add a code such as AA or AA-XXX "
                "or provide a Flag Override URL."
            )

        if override:
            if not is_web_url(override):
                errors.append(
                    f"Flag Override for {country} must be a public direct image URL "
                    "beginning with https://."
                )
            elif override.lower().startswith("http://"):
                warnings.append(
                    f"Flag Override for {country} uses http://; https:// is recommended."
                )
        elif not resolved_flag:
            warnings.append(
                f"Flag/emblem could not be resolved automatically for {country} "
                f"({code or 'no code'})."
            )

    duplicate_codes = sorted({code for code in codes if codes.count(code) > 1})
    for code in duplicate_codes:
        warnings.append(f"Country code '{code}' is used by more than one participant.")

    for label, asset_value in (
        ("Background", background_file),
        ("Logo", logo_file),
        ("Backsound", backsound_file),
    ):
        asset_value = clean_text(asset_value)
        if asset_value and not is_web_url(asset_value) and not Path(asset_value).exists():
            warnings.append(f"{label} file was not found: {asset_value}")

    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    return errors, warnings
