
import time
from collections import defaultdict

import streamlit as st


# All Streamlit session-state defaults live in one place. Callable values create
# a fresh mutable object for each session, avoiding shared lists/dictionaries.
SESSION_STATE_DEFAULTS = {
    "totals": lambda: defaultdict(int),
    "voter_idx": 0,
    "point_idx": 0,
    "group_idx": 0,
    "revealed_log": list,
    "hod_revealed": False,
    "fly_entries": list,
    "animation_nonce": 0,
    "animation_snapshot": None,
    # While a reveal animation is running, lock Reveal/Undo until landing.
    "animation_locked_until": 0.0,
    "entered_voting_arena": False,
    "show_final_standing": False,
    # True for exactly one render after opening the arena/final page.
    "arena_entry_animation": False,
    # A changing nonce forces the page-entry CSS animation to replay.
    "page_entry_animation_nonce": 0,
    # True on fresh load and whenever returning to the landing page.
    "landing_entry_animation": True,
}

VOTING_RESET_KEYS = (
    "totals",
    "voter_idx",
    "point_idx",
    "group_idx",
    "revealed_log",
    "hod_revealed",
    "fly_entries",
    "animation_snapshot",
    "animation_nonce",
    "animation_locked_until",
    "show_final_standing",
)


def make_state_default(key):
    """Return a fresh default value for one session-state key."""
    default = SESSION_STATE_DEFAULTS[key]
    return default() if callable(default) else default


def initialize_session_state():
    """Create any missing session-state keys without overwriting live progress."""
    for key in SESSION_STATE_DEFAULTS:
        if key not in st.session_state:
            st.session_state[key] = make_state_default(key)


def pending_animation_duration_ms(entry_count, animation_cfg):
    if entry_count <= 0:
        return 0
    return (
        animation_cfg.ball_flight_ms
        + ((entry_count - 1) * animation_cfg.ball_stagger_ms)
        + animation_cfg.ball_after_pad_ms
    )


def animation_is_active():
    return time.time() < float(st.session_state.get("animation_locked_until", 0.0) or 0.0)


def clear_animation_state():
    st.session_state.fly_entries = []
    st.session_state.animation_snapshot = None
    st.session_state.animation_locked_until = 0.0


def current_voter(voting_countries):
    if not voting_countries:
        return ""
    idx = min(st.session_state.voter_idx, len(voting_countries) - 1)
    return voting_countries[idx]


def vote_recipient(voter_idx, points, voting_countries, point_to_row, voter_col_by_country, votes_df, clean_text_func):
    if points not in point_to_row or not voting_countries:
        return ""

    row = point_to_row[points]
    voter_country = voting_countries[min(voter_idx, len(voting_countries) - 1)]
    col = voter_col_by_country.get(voter_country)

    if col is None or col >= votes_df.shape[1]:
        return ""

    return clean_text_func(votes_df.iloc[row, col])


def reveal_next(
    *,
    voting_countries,
    countries,
    country_info,
    points_order,
    reveal_groups,
    animation_cfg,
    point_to_row,
    voter_col_by_country,
    votes_df,
    clean_text_func,
    build_ranking_dataframe_fn,
):
    # Prevent accidental double-clicks while balls are still flying / rows sliding.
    if animation_is_active():
        return

    # First click reveals the HoD name before any points are assigned.
    if not st.session_state.hod_revealed:
        st.session_state.hod_revealed = True
        clear_animation_state()
        return

    if st.session_state.group_idx >= len(reveal_groups):
        if st.session_state.voter_idx >= len(voting_countries) - 1:
            clear_animation_state()
            st.session_state.show_final_standing = True
        else:
            next_voter(voting_countries)
        return

    current_group = reveal_groups[st.session_state.group_idx]

    pre_df = build_ranking_dataframe_fn(
        countries=countries,
        country_info=country_info,
        points_order=points_order,
        totals=st.session_state.totals,
        revealed_log=st.session_state.revealed_log,
    )
    pre_order = pre_df["Country"].tolist()
    pre_slot_by_country = {country: idx for idx, country in enumerate(pre_order)}

    fly_entries = []
    for points in current_group:
        recipient = vote_recipient(
            st.session_state.voter_idx,
            points,
            voting_countries,
            point_to_row,
            voter_col_by_country,
            votes_df,
            clean_text_func,
        )
        if recipient:
            fly_entries.append({
                "Recipient": recipient,
                "Points": points,
                "Slot": pre_slot_by_country.get(recipient, 0),
            })

    for entry in fly_entries:
        recipient = entry.get("Recipient", "")
        points = int(entry.get("Points", 0) or 0)
        if recipient:
            st.session_state.totals[recipient] += points
            st.session_state.revealed_log.append({
                "Voter": current_voter(voting_countries),
                "Recipient": recipient,
                "Points": points,
            })

    st.session_state.group_idx += 1
    st.session_state.point_idx += len(current_group)

    post_df = build_ranking_dataframe_fn(
        countries=countries,
        country_info=country_info,
        points_order=points_order,
        totals=st.session_state.totals,
        revealed_log=st.session_state.revealed_log,
    )
    post_order = post_df["Country"].tolist()

    duration_ms = pending_animation_duration_ms(len(fly_entries), animation_cfg)
    st.session_state.fly_entries = fly_entries
    st.session_state.animation_nonce += 1
    st.session_state.animation_snapshot = {
        "nonce": st.session_state.animation_nonce,
        "pre_order": pre_order,
        "post_order": post_order,
        "duration_ms": duration_ms,
        "row_delay_ms": duration_ms,
    }
    st.session_state.animation_locked_until = time.time() + (
        (duration_ms + animation_cfg.row_slide_ms + animation_cfg.button_lock_buffer_ms) / 1000.0
    )


def undo_last(voting_countries, reveal_groups):
    if animation_is_active():
        return

    clear_animation_state()

    # When no score group has been revealed for the current voter yet, Undo
    # should only hide that voter's HoD. Check this before revealed_log,
    # because its last entry may still belong to the previous voter.
    if st.session_state.group_idx == 0 and st.session_state.hod_revealed:
        st.session_state.hod_revealed = False
        return

    if not st.session_state.revealed_log:
        return

    if st.session_state.revealed_log[-1].get("Voter") != current_voter(voting_countries):
        return

    if st.session_state.group_idx <= 0:
        return

    last_group = reveal_groups[st.session_state.group_idx - 1]

    for _ in last_group:
        if not st.session_state.revealed_log:
            break
        if st.session_state.revealed_log[-1].get("Voter") != current_voter(voting_countries):
            break

        last = st.session_state.revealed_log.pop()
        recipient = last.get("Recipient", "")
        points = int(last.get("Points", 0) or 0)

        if recipient:
            st.session_state.totals[recipient] -= points
            if st.session_state.totals[recipient] < 0:
                st.session_state.totals[recipient] = 0

    st.session_state.group_idx -= 1
    st.session_state.point_idx -= len(last_group)
    if st.session_state.point_idx < 0:
        st.session_state.point_idx = 0


def next_voter(voting_countries):
    if st.session_state.voter_idx < len(voting_countries) - 1:
        st.session_state.voter_idx += 1
        st.session_state.point_idx = 0
        st.session_state.group_idx = 0
        st.session_state.hod_revealed = False
        clear_animation_state()


def reset_state_keys(keys):
    """Restore selected session-state keys to their centralized defaults."""
    for key in keys:
        st.session_state[key] = make_state_default(key)


def reset_all():
    # Preserve the current page behavior from the stable Stage 2 version:
    # reset voting progress, but do not force the user out of the arena.
    reset_state_keys(VOTING_RESET_KEYS)


def enter_voting_arena():
    st.session_state.entered_voting_arena = True
    st.session_state.show_final_standing = False
    st.session_state.arena_entry_animation = True
    st.session_state.page_entry_animation_nonce += 1


def open_final_standing():
    st.session_state.entered_voting_arena = True
    st.session_state.show_final_standing = True
    st.session_state.arena_entry_animation = True
    st.session_state.page_entry_animation_nonce += 1


def back_to_start():
    st.session_state.show_final_standing = False
    st.session_state.entered_voting_arena = False
    st.session_state.landing_entry_animation = True
    st.session_state.page_entry_animation_nonce += 1


def go_home():
    """Return to the mode-selection home without discarding the uploaded edition.

    Voting progress is intentionally preserved. Changing or clearing the uploaded
    edition remains a separate, explicit action on the home/setup screens.
    """
    clear_animation_state()
    st.session_state.app_mode = None
    st.session_state.entered_voting_arena = False
    st.session_state.show_final_standing = False
    st.session_state.rehearsal_no_animation = False
    st.session_state.landing_entry_animation = True
    st.session_state.page_entry_animation_nonce += 1
