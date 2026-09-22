import base64
import html
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
FLAG_LOADER_VERSION = "deploy-split-workbooks-v3-optional-televote-auto-dq-20260922"
FLAG_CDN_BASE = "https://flagcdn.com"
COMMONS_FILEPATH_BASE = "https://commons.wikimedia.org/wiki/Special:FilePath/"
COUNTRY_CODE_ALIASES = {
    "UK": "GB",  # Common informal code for the United Kingdom.
    "EL": "GR",  # Common alternative code for Greece.
    "UK-ENG": "GB-ENG",
    "UK-SCT": "GB-SCT",
    "UK-WLS": "GB-WLS",
    "UK-NIR": "GB-NIR",
    "ID-PP": "ID-PB",  # Common shorthand for West Papua.
}

CANADA_SUBDIVISION_FILES = {
    "CA-AB": "Flag of Alberta.svg",
    "CA-BC": "Flag of British Columbia.svg",
    "CA-MB": "Flag of Manitoba.svg",
    "CA-NB": "Flag of New Brunswick.svg",
    "CA-NL": "Flag of Newfoundland and Labrador.svg",
    "CA-NS": "Flag of Nova Scotia.svg",
    "CA-NT": "Flag of the Northwest Territories.svg",
    "CA-NU": "Flag of Nunavut.svg",
    "CA-ON": "Flag of Ontario.svg",
    "CA-PE": "Flag of Prince Edward Island.svg",
    "CA-QC": "Flag of Quebec.svg",
    "CA-SK": "Flag of Saskatchewan.svg",
    "CA-YT": "Flag of Yukon.svg",
}

UK_NATION_FILES = {
    "GB-ENG": "Flag of England.svg",
    "GB-SCT": "Flag of Scotland.svg",
    "GB-WLS": "Flag of Wales 2.svg",
    "GB-NIR": "Ulster Banner.svg",
}

AU_SUBDIVISION_FILES = {
    "AU-NSW": "Flag of New South Wales.svg",
    "AU-VIC": "Flag of Victoria (Australia).svg",
    "AU-QLD": "Flag of Queensland.svg",
    "AU-WA": "Flag of Western Australia.svg",
    "AU-SA": "Flag of South Australia.svg",
    "AU-TAS": "Flag of Tasmania.svg",
    "AU-ACT": "Flag of the Australian Capital Territory.svg",
    "AU-NT": "Flag of the Northern Territory.svg",
}

DE_SUBDIVISION_FILES = {
    "DE-BW": "Flag of Baden-Württemberg.svg",
    "DE-BY": "Flag of Bavaria (striped).svg",
    "DE-BE": "Flag of Berlin.svg",
    "DE-BB": "Flag of Brandenburg.svg",
    "DE-HB": "Flag of Bremen.svg",
    "DE-HH": "Flag of Hamburg.svg",
    "DE-HE": "Flag of Hesse.svg",
    "DE-MV": "Flag of Mecklenburg-Western Pomerania.svg",
    "DE-NI": "Flag of Lower Saxony.svg",
    "DE-NW": "Flag of North Rhine-Westphalia.svg",
    "DE-RP": "Flag of Rhineland-Palatinate.svg",
    "DE-SL": "Flag of Saarland.svg",
    "DE-SN": "Flag of Saxony.svg",
    "DE-ST": "Flag of Saxony-Anhalt.svg",
    "DE-SH": "Flag of Schleswig-Holstein.svg",
    "DE-TH": "Flag of Thuringia.svg",
}

ES_SUBDIVISION_FILES = {
    "ES-AN": "Flag of Andalusia.svg",
    "ES-AR": "Flag of Aragon.svg",
    "ES-AS": "Flag of Asturias.svg",
    "ES-CN": "Flag of the Canary Islands.svg",
    "ES-CB": "Flag of Cantabria.svg",
    "ES-CL": "Flag of Castile and León.svg",
    "ES-CM": "Flag of Castilla-La Mancha.svg",
    "ES-CT": "Flag of Catalonia.svg",
    "ES-EX": "Flag of Extremadura.svg",
    "ES-GA": "Flag of Galicia.svg",
    "ES-IB": "Flag of the Balearic Islands.svg",
    "ES-RI": "Flag of La Rioja.svg",
    "ES-MD": "Flag of the Community of Madrid.svg",
    "ES-MC": "Flag of the Region of Murcia.svg",
    "ES-NC": "Flag of Navarre.svg",
    "ES-PV": "Flag of the Basque Country.svg",
    "ES-VC": "Flag of the Valencian Community.svg",
    "ES-CE": "Flag of Ceuta.svg",
    "ES-ML": "Flag of Melilla.svg",
}

ID_EMBLEM_FILES = {
    "ID-AC": "Coat of arms of Aceh.svg",
    "ID-SU": "Coat of arms of North Sumatra.svg",
    "ID-SB": "Coat of arms of West Sumatra.svg",
    "ID-RI": "Coat of arms of Riau.svg",
    "ID-JA": "Coat of arms of Jambi.svg",
    "ID-SS": "Coat of arms of South Sumatra.svg",
    "ID-BB": "Coat of arms of Bangka Belitung Islands.svg",
    "ID-BE": "Coat of arms of Bengkulu.svg",
    "ID-LA": "Coat of arms of Lampung.svg",
    "ID-KR": "Coat of arms of Riau Islands.svg",
    "ID-JK": "Coat of arms of Jakarta.svg",
    "ID-JB": "Coat of arms of West Java.svg",
    "ID-BT": "Coat of arms of Banten.svg",
    "ID-JT": "Coat of arms of Central Java.svg",
    "ID-YO": "Coat of arms of Special Region of Yogyakarta.svg",
    "ID-JI": "Coat of arms of East Java.svg",
    "ID-BA": "Coat of arms of Bali.svg",
    "ID-NB": "Coat of arms of West Nusa Tenggara.svg",
    "ID-NT": "Coat of arms of East Nusa Tenggara.svg",
    "ID-KB": "Coat of arms of West Kalimantan.svg",
    "ID-KT": "Coat of arms of Central Kalimantan.svg",
    "ID-KI": "Coat of arms of East Kalimantan.svg",
    "ID-KS": "Coat of arms of South Kalimantan.svg",
    "ID-KU": "Coat of arms of North Kalimantan.svg",
    "ID-SA": "Coat of arms of North Sulawesi.svg",
    "ID-ST": "Coat of arms of Central Sulawesi.svg",
    "ID-SG": "Coat of arms of Southeast Sulawesi.svg",
    "ID-SR": "Coat of arms of West Sulawesi.svg",
    "ID-SN": "Coat of arms of South Sulawesi.svg",
    "ID-GO": "Coat of arms of Gorontalo.svg",
    "ID-MA": "Coat of arms of Maluku.svg",
    "ID-MU": "Coat of arms of North Maluku.svg",
    "ID-PA": "Coat of arms of Papua.svg",
    "ID-PB": "Coat of arms of West Papua.svg",
    "ID-PT": "Coat of arms of Central Papua.svg",
    "ID-PE": "Coat of arms of Highland Papua.svg",
    "ID-PS": "Coat of arms of South Papua.svg",
    "ID-PD": "Coat of arms of Southwest Papua.svg",
}



class WorkbookLoadError(ValueError):
    """Raised when an uploaded workbook cannot be interpreted safely."""

SPECIAL_SUBDIVISION_FILES = {
    "US-DC": "Flag of Washington, D.C..svg",
    **CANADA_SUBDIVISION_FILES,
    **UK_NATION_FILES,
    **AU_SUBDIVISION_FILES,
    **DE_SUBDIVISION_FILES,
    **ES_SUBDIVISION_FILES,
    **ID_EMBLEM_FILES,
}


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_voting_name(value):
    """Return (visible name, is_televote) for a spreadsheet name.

    A trailing * is an internal marker, never part of the displayed name.
    Plain names continue to work unchanged for editions without televoting.
    """
    name = clean_text(value)
    is_televote = name.endswith("*")
    return (name[:-1].strip() if is_televote else name), is_televote


def is_web_url(value):
    value = clean_text(value).lower()
    return value.startswith("https://") or value.startswith("http://")


def normalize_country_code(value):
    """Return a normalized country/subdivision code, or an empty string."""
    code = clean_text(value).upper().replace("_", "-").replace(" ", "")
    code = re.sub(r"[^A-Z0-9-]", "", code)
    code = COUNTRY_CODE_ALIASES.get(code, code)

    if re.fullmatch(r"[A-Z]{2}", code):
        return code

    if re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", code):
        country, subdivision = code.split("-", 1)
        country = COUNTRY_CODE_ALIASES.get(country, country)
        normalized = f"{country}-{subdivision}"
        normalized = COUNTRY_CODE_ALIASES.get(normalized, normalized)
        return normalized

    return ""


def commons_file_url(filename):
    filename = clean_text(filename)
    if not filename:
        return ""
    return f"{COMMONS_FILEPATH_BASE}{quote(filename)}"


def flag_url_for_code(code):
    """Build the default SVG flag/emblem URL for a supported code."""
    normalized = normalize_country_code(code)
    if not normalized:
        return ""

    if normalized in SPECIAL_SUBDIVISION_FILES:
        return commons_file_url(SPECIAL_SUBDIVISION_FILES[normalized])

    if re.fullmatch(r"US-[A-Z]{2}", normalized):
        return f"{FLAG_CDN_BASE}/{normalized.lower()}.svg"

    if re.fullmatch(r"[A-Z]{2}", normalized):
        return f"{FLAG_CDN_BASE}/{normalized.lower()}.svg"

    return ""


def resolve_flag_source(code="", override=""):
    """Use a custom flag when supplied; otherwise use the automatic code flag."""
    override = clean_text(override)
    return override or flag_url_for_code(code)


def image_to_data_uri(value):
    value = clean_text(value)
    if not value:
        return ""

    # Remote images such as automatic country flags can be used directly by
    # the browser. Local project assets are still embedded as data URIs.
    if is_web_url(value):
        return value

    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path

    if not path.exists():
        return ""

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def flag_html(value, w=74, h=50, circle=True, fallback=""):
    value = clean_text(value)
    image_source = image_to_data_uri(value)
    fallback_source = image_to_data_uri(fallback)

    radius = "999px" if circle else "0px"

    if image_source:
        safe_source = html.escape(image_source, quote=True)
        fallback_attr = ""
        if fallback_source and fallback_source != image_source:
            safe_fallback = html.escape(fallback_source, quote=True)
            fallback_attr = (
                f' data-fallback-src="{safe_fallback}" '
                f'onerror="if(this.dataset.fallbackSrc&&!this.dataset.alcFallbackUsed)'
                f'{{this.dataset.alcFallbackUsed=\'1\';this.src=this.dataset.fallbackSrc;}}"'
            )
        return (
            f'<img class="flag-img" src="{safe_source}"{fallback_attr} '
            f'style="width:{w}px;height:{h}px;border-radius:{radius};" '
            f'alt="" loading="eager">'
        )

    if value:
        safe_value = html.escape(value, quote=True)
        return f'<div class="flag-text" style="width:{w}px;height:{h}px;border-radius:{radius};">{safe_value}</div>'

    return f'<div class="flag-empty" style="width:{w}px;height:{h}px;border-radius:{radius};"></div>'


def load_title(elements_file):
    """Read Title and Host City from the uploaded Elements workbook."""
    try:
        elements = pd.read_excel(elements_file, sheet_name="Elements", header=None)
    except Exception as exc:
        raise WorkbookLoadError(f"Could not read the Elements sheet: {exc}") from exc

    values = {}
    for row_idx in range(len(elements)):
        key = clean_text(elements.iloc[row_idx, 0] if elements.shape[1] > 0 else "").upper()
        value = clean_text(elements.iloc[row_idx, 1] if elements.shape[1] > 1 else "")
        if key:
            values[key] = value

    return values.get("TITLE", ""), values.get("HOST CITY", values.get("HOST", ""))


def _find_column(columns, aliases):
    alias_lookup = {alias.upper() for alias in aliases}
    return next((column for column in columns if clean_text(column).upper() in alias_lookup), None)


def load_data(excel_file):
    try:
        participants = pd.read_excel(excel_file, sheet_name="Participants")
        votes = pd.read_excel(excel_file, sheet_name="Votes", header=None)
    except Exception as exc:
        raise WorkbookLoadError(f"Could not read the Votes workbook: {exc}") from exc

    participants.columns = [clean_text(c) for c in participants.columns]

    required = ["Country", "HoD"]
    missing = [column for column in required if column not in participants.columns]
    if missing:
        raise WorkbookLoadError(
            "Missing column(s) in Participants sheet: " + ", ".join(missing)
        )

    number_col = _find_column(
        participants.columns,
        ["#", "No", "NO", "Number", "Running Order"],
    )
    code_col = _find_column(
        participants.columns,
        ["Code", "Country Code", "ISO2", "ISO 2", "ISO Code"],
    )
    flag_override_col = _find_column(
        participants.columns,
        ["Flag Override", "Flag (Optional)", "Custom Flag", "Flag"],
    )

    if not code_col and not flag_override_col:
        raise WorkbookLoadError(
            "Participants must contain a Code column for automatic flags "
            "or a Flag Override column for custom flag links."
        )

    selected_columns = ([number_col] if number_col else []) + ["Country"]
    if code_col:
        selected_columns.append(code_col)
    selected_columns.append("HoD")
    if flag_override_col:
        selected_columns.append(flag_override_col)

    participants = participants[selected_columns].copy()

    rename_map = {}
    if number_col:
        rename_map[number_col] = "ParticipantNo"
    if code_col:
        rename_map[code_col] = "Code"
    if flag_override_col:
        rename_map[flag_override_col] = "FlagOverride"
    participants = participants.rename(columns=rename_map)

    if "ParticipantNo" not in participants.columns:
        participants.insert(0, "ParticipantNo", range(1, len(participants) + 1))
    if "Code" not in participants.columns:
        participants["Code"] = ""
    if "FlagOverride" not in participants.columns:
        participants["FlagOverride"] = ""

    for column in ["Country", "HoD", "Code", "FlagOverride"]:
        participants[column] = participants[column].apply(clean_text)

    participants = participants[participants["Country"] != ""].reset_index(drop=True)
    # The optional televote has metadata (flag/HoD) for its calling screen,
    # but is never a contestant in rankings or the scoreboard.
    parsed_names = participants["Country"].apply(parse_voting_name)
    participants["IsTelevote"] = parsed_names.apply(lambda parsed: parsed[1])
    participants["Country"] = parsed_names.apply(lambda parsed: parsed[0])
    televote_rows = participants[participants["IsTelevote"]]
    if len(televote_rows) > 1:
        raise WorkbookLoadError(
            "Only one televote is allowed per edition. Combine televotes into "
            "a single marked (*) row in Participants and a single voting column."
        )
    if any(not name for name in participants["Country"]):
        raise WorkbookLoadError("A participant or televote name cannot consist only of '*'.")
    if participants["Country"].duplicated().any() and not televote_rows.empty:
        # Also catches a televote whose visible name duplicates a contestant.
        duplicated = participants.loc[participants["Country"].duplicated(False), "Country"].tolist()
        if any(name == televote_rows.iloc[0]["Country"] for name in duplicated):
            raise WorkbookLoadError(
                "Televote must have a distinct name from every participant."
            )
    participants["ParticipantNo"] = pd.to_numeric(
        participants["ParticipantNo"], errors="coerce"
    )
    fallback_numbers = pd.Series(
        range(1, len(participants) + 1), index=participants.index
    )
    participants["ParticipantNo"] = (
        participants["ParticipantNo"].fillna(fallback_numbers).astype(int)
    )
    participants["Code"] = participants["Code"].apply(normalize_country_code)
    participants["DefaultFlag"] = participants["Code"].apply(flag_url_for_code)
    participants["Flag"] = participants.apply(
        lambda row: resolve_flag_source(row["Code"], row["FlagOverride"]),
        axis=1,
    )
    participants["FallbackFlag"] = participants.apply(
        lambda row: row["DefaultFlag"] if row["FlagOverride"] else "",
        axis=1,
    )

    country_info = {}
    for _, row in participants.iterrows():
        country_info[row["Country"]] = {
            "HoD": row["HoD"],
            "Code": row["Code"],
            "FlagOverride": row["FlagOverride"],
            "Flag": row["Flag"],
            "FallbackFlag": row["FallbackFlag"],
            "No": int(row["ParticipantNo"]),
            "IsTelevote": bool(row["IsTelevote"]),
            "IsDQ": False,
        }

    participants = participants[~participants["IsTelevote"]].copy().reset_index(drop=True)

    # Voting order follows the physical left-to-right order in the Votes sheet.
    voter_col_by_country = {}
    voting_countries = []
    televote_voter_count = 0
    for col_idx, value in enumerate(votes.iloc[1, 1:].tolist(), start=1):
        value, marked_televote = parse_voting_name(value)
        if value:
            if marked_televote:
                televote_voter_count += 1
                if televote_voter_count > 1:
                    raise WorkbookLoadError(
                        "Only one marked (*) televote column is allowed in Votes. "
                        "Combine televotes into one set of points."
                    )
            info = country_info.get(value)
            if info is not None and bool(info["IsTelevote"]) != marked_televote:
                raise WorkbookLoadError(
                    f"The (*) televote marker for '{value}' must match in "
                    "Participants and Votes."
                )
            voter_col_by_country[value] = col_idx
            voting_countries.append(value)

    # A contestant without a voting column is automatically disqualified.
    # The contestant stays in Participants / country_info so votes received
    # remain auditable; only the competitive ranking treats them differently.
    participants["IsDQ"] = ~participants["Country"].isin(voting_countries)
    for _, row in participants.iterrows():
        country_info[row["Country"]]["IsDQ"] = bool(row["IsDQ"])

    point_to_row = {}
    for row_idx in range(2, len(votes)):
        raw_point = votes.iloc[row_idx, 0]
        if pd.isna(raw_point):
            continue
        try:
            point_to_row[int(raw_point)] = row_idx
        except Exception:
            pass

    return (
        participants,
        country_info,
        votes,
        voting_countries,
        point_to_row,
        voter_col_by_country,
    )


def load_palette(excel_file):
    """
    Reads the Palette sheet.

    Current grouped layout:
      Column A = color group (informational only)
      Column B = one or more object keys, separated by semicolons
      Column C = HEX color
      Column D = human-readable color name (informational only)

    The older two-column layout (Object | Palette) is also supported.
    """
    try:
        palette_df = pd.read_excel(excel_file, sheet_name="Palette", header=None)
    except Exception as exc:
        raise WorkbookLoadError(f"Could not read the Palette sheet: {exc}") from exc

    palette = {}

    # Detect layout from the header row.
    headers = [
        clean_text(palette_df.iloc[0, col]).upper()
        if palette_df.shape[0] > 0 and col < palette_df.shape[1]
        else ""
        for col in range(palette_df.shape[1])
    ]

    if "OBJECT" in headers and "CODE" in headers:
        object_col = headers.index("OBJECT")
        value_col = headers.index("CODE")
    else:
        # Backward-compatible fallback for the original two-column sheet.
        object_col = 0
        value_col = 1

    for row_idx in range(1, len(palette_df)):
        raw_objects = clean_text(
            palette_df.iloc[row_idx, object_col]
            if object_col < palette_df.shape[1]
            else ""
        )
        value = clean_text(
            palette_df.iloc[row_idx, value_col]
            if value_col < palette_df.shape[1]
            else ""
        ).upper()

        if not raw_objects:
            continue

        # A grouped row may control several CSS objects, e.g.
        # "TITLE_TEXT; TITLE_DIVIDER_SYMBOL".
        object_keys = [
            item.strip().upper()
            for item in raw_objects.split(";")
            if item.strip()
        ]

        for key in object_keys:
            palette[key] = value

    required_keys = [
        "PAGE_OVERLAY",
        "TITLE_BG_TOP", "TITLE_BG_BOTTOM", "TITLE_BG_GLOW", "TITLE_BORDER",
        "TITLE_TEXT", "TITLE_TEXT_SHADOW", "TITLE_DIVIDER_DARK",
        "TITLE_DIVIDER_LIGHT", "TITLE_DIVIDER_SYMBOL", "TITLE_SUBTITLE_TEXT",
        "TITLE_DIVIDER_BG",
        "NOW_VOTING_TEXT", "NOW_VOTING_DECORATION",
        "RIGHT_PANEL_BG_TOP", "RIGHT_PANEL_BG_BOTTOM", "RIGHT_PANEL_BORDER",
        "VOTER_COUNTRY_TEXT",
        "HOD_CARD_LIGHT", "HOD_CARD_MID", "HOD_CARD_DARK", "HOD_CARD_BORDER",
        "HOD_LABEL_TEXT", "HOD_NAME_TEXT",
        "VOTE_STATUS_LABEL", "VOTE_STATUS_NUMBER",
        "PROGRESS_TRACK_DARK", "PROGRESS_TRACK_LIGHT",
        "PROGRESS_LIGHT", "PROGRESS_MID", "PROGRESS_DARK",
        "BUTTON_LIGHT", "BUTTON_MID", "BUTTON_DARK", "BUTTON_TEXT",
        "SCORE_RANK_BG", "SCORE_RANK_TEXT",
        "SCORE_COUNTRY_BG", "SCORE_COUNTRY_TEXT",
        "SCORE_POINTS_BG", "SCORE_POINTS_TEXT", "SCORE_GAIN_TEXT",
        "SCORE_ROW_BORDER", "FLAG_PLACEHOLDER",
        "POINT_BUBBLE_LIGHT", "POINT_BUBBLE_MID", "POINT_BUBBLE_DARK",
        "POINT_BUBBLE_TEXT", "POINT_BUBBLE_BORDER",
        "POINT_DISABLED_LIGHT", "POINT_DISABLED_MID", "POINT_DISABLED_DARK",
        "POINT_EMPTY_BORDER",
        "FLYING_BALL_LIGHT", "FLYING_BALL_MID", "FLYING_BALL_DARK",
        "FLYING_BALL_TEXT",
        "GENERAL_WHITE", "GENERAL_DARK_TEXT", "GENERAL_BLACK",
    ]

    missing = [key for key in required_keys if not palette.get(key)]
    invalid = [
        key for key in required_keys
        if palette.get(key) and not re.fullmatch(r"#[0-9A-F]{6}", palette[key])
    ]

    palette_errors = []
    if missing:
        palette_errors.append(
            "Missing palette key(s): " + ", ".join(missing)
        )
    if invalid:
        palette_errors.append(
            "Invalid HEX value(s); use #RRGGBB for: " + ", ".join(invalid)
        )
    if palette_errors:
        raise WorkbookLoadError("Palette sheet: " + " | ".join(palette_errors))

    return palette


def css_var_name(key):
    return "--alc-" + key.lower().replace("_", "-")


def build_palette_css_variables(palette):
    declarations = "\n".join(
        f"    {css_var_name(key)}: {value};"
        for key, value in palette.items()
        if re.fullmatch(r"#[0-9A-F]{6}", value)
    )
    return f":root {{\n{declarations}\n}}"


def hex_to_rgba(hex_color, alpha):
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"
