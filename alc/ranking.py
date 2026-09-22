"""Pure ranking logic for the ALC scoreboard.

This module intentionally has no Streamlit dependency, so ranking and
tiebreak behavior can be tested independently from the user interface.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd


def build_ranking_dataframe(
    *,
    countries: Sequence[str],
    country_info: Mapping[str, Mapping[str, Any]],
    points_order: Sequence[int],
    totals: Mapping[str, int],
    revealed_log: Sequence[Mapping[str, Any]],
) -> pd.DataFrame:
    """Build standings using points and the full ALC tiebreak sequence.

    Tiebreak order:
      1. Total points
      2. Number of voters awarding points
      3. Number of highest-value awards, descending through all point values
      4. Country name alphabetically as a deterministic final fallback

    Contestants without a voting column are marked IsDQ in country_info.
    Their raw points remain in the returned data for internal bookkeeping,
    but they always appear after ranked contestants, alphabetically within DQ.
    """
    descending_points = sorted(points_order, reverse=True)

    country_vote_stats: dict[str, dict[str, int]] = {}
    for country in countries:
        stats = {"voters_count": 0}
        for points in points_order:
            stats[f"count_{points}"] = 0
        country_vote_stats[country] = stats

    for revealed in revealed_log:
        recipient = str(revealed.get("Recipient", "")).strip()
        try:
            points = int(revealed.get("Points", 0) or 0)
        except (TypeError, ValueError):
            continue

        if recipient not in country_vote_stats:
            continue

        count_key = f"count_{points}"
        if count_key not in country_vote_stats[recipient]:
            continue

        country_vote_stats[recipient]["voters_count"] += 1
        country_vote_stats[recipient][count_key] += 1

    rows: list[dict[str, Any]] = []
    for country in countries:
        stats = country_vote_stats[country]
        info = country_info.get(country, {})
        row: dict[str, Any] = {
            "Country": country,
            "Flag": info.get("Flag", ""),
            "FallbackFlag": info.get("FallbackFlag", ""),
            "Points": int(totals.get(country, 0) or 0),
            "Voters": stats["voters_count"],
            "IsDQ": bool(info.get("IsDQ", False)),
        }
        for points in descending_points:
            row[f"P{points}"] = stats[f"count_{points}"]
        rows.append(row)

    dataframe = pd.DataFrame(rows)
    sort_columns = (
        ["Points", "Voters"]
        + [f"P{points}" for points in descending_points]
        + ["Country"]
    )
    sort_ascending = [False] * (len(sort_columns) - 1) + [True]

    active = dataframe.loc[~dataframe["IsDQ"]].sort_values(
        by=sort_columns,
        ascending=sort_ascending,
    )
    disqualified = dataframe.loc[dataframe["IsDQ"]].sort_values(by="Country")
    dataframe = pd.concat([active, disqualified], ignore_index=True)
    dataframe.index += 1
    return dataframe
