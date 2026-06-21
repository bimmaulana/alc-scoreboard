import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side

from .flag_loader import clean_text
from .ranking import build_ranking_dataframe

def build_complete_vote_data(
    countries, voting_countries, voter_col_by_country, votes_df,
    point_to_row, country_info, points_order,
):
    """Return the full final vote matrix and ranking from the input workbook."""
    full_totals = defaultdict(int)
    full_log = []
    vote_matrix = {country: {} for country in countries}

    for voter_country in voting_countries:
        col = voter_col_by_country.get(voter_country)
        if col is None:
            continue
        voter_hod = country_info.get(voter_country, {}).get("HoD", voter_country)
        for points in points_order:
            row = point_to_row.get(points)
            if row is None or col >= votes_df.shape[1]:
                continue
            recipient = clean_text(votes_df.iloc[row, col])
            if not recipient:
                continue
            full_totals[recipient] += int(points)
            full_log.append({"Voter": voter_country, "Recipient": recipient, "Points": int(points)})
            vote_matrix.setdefault(recipient, {})[voter_country] = int(points)

    return full_totals, full_log, vote_matrix


def build_result_excel_bytes(
    participants_df, country_info, votes_df, voting_countries,
    point_to_row, voter_col_by_country, countries, points_order,
):
    """Create the downloadable Voting Grid without requiring XlsxWriter."""
    full_totals, full_log, vote_matrix = build_complete_vote_data(
        countries=countries,
        voting_countries=voting_countries,
        voter_col_by_country=voter_col_by_country,
        votes_df=votes_df,
        point_to_row=point_to_row,
        country_info=country_info,
        points_order=points_order,
    )
    final_ranking = build_ranking_dataframe(
        countries=countries,
        country_info=country_info,
        points_order=points_order,
        totals=full_totals,
        revealed_log=full_log,
    )

    # Downloaded result columns follow Participants running order (#),
    # while the Streamlit reveal sequence still follows the Votes sheet order.
    # Header text is the exact HoD name.
    ordered_voters = [
        country for country in participants_df.sort_values("ParticipantNo")["Country"].tolist()
        if country in voter_col_by_country
    ]
    headers = ["No", "HOD", "Country", "Sum", "Rk", "# Votes", "# 20 pts"] + [
        country_info.get(c, {}).get("HoD", c) for c in ordered_voters
    ]

    output = io.BytesIO()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    worksheet.sheet_view.showGridLines = False
    worksheet.sheet_view.zoomScale = 75

    thin_black = Side(style="thin", color="000000")
    cell_border = Border(left=thin_black, right=thin_black, top=thin_black, bottom=thin_black)
    value_font = Font(name="Helvetica Neue", size=10)
    blank_font = Font(name="Helvetica", size=12)
    centered = Alignment(horizontal="center", vertical="center")

    # Column widths roughly match the previous XlsxWriter export.
    widths = {
        "A": 3.33, "B": 9.83, "C": 13.50, "D": 4.66,
        "E": 4.16, "F": 7.00, "G": 7.50,
    }
    for col_letter, width in widths.items():
        worksheet.column_dimensions[col_letter].width = width

    # Voter columns begin at H.
    from openpyxl.utils import get_column_letter
    for col_idx in range(8, 8 + len(ordered_voters)):
        worksheet.column_dimensions[get_column_letter(col_idx)].width = 10.00

    # Header row.
    for col_idx, header in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=col_idx, value=header)
        cell.font = value_font
        cell.alignment = centered
        cell.border = cell_border

    # build_ranking_dataframe uses a 1-based index; preserve that exact Rk.
    for out_row, (rank, row) in enumerate(final_ranking.iterrows(), start=2):
        country = row["Country"]
        info = country_info.get(country, {})
        values = [
            info.get("No", ""),
            info.get("HoD", ""),
            country,
            int(row["Points"]),
            int(rank),
            int(row["Voters"]),
            int(row.get("P20", 0)),
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = worksheet.cell(row=out_row, column=col_idx, value=value)
            cell.font = value_font
            cell.alignment = centered
            cell.border = cell_border

        for voter_offset, voter_country in enumerate(ordered_voters, start=8):
            points = vote_matrix.get(country, {}).get(voter_country)
            cell = worksheet.cell(row=out_row, column=voter_offset, value=points)
            cell.font = value_font if points is not None else blank_font
            cell.alignment = centered
            cell.border = cell_border

    for row_idx in range(1, worksheet.max_row + 1):
        worksheet.row_dimensions[row_idx].height = 16

    workbook.save(output)
    output.seek(0)
    return output.getvalue()
