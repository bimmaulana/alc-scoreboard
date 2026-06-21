from dataclasses import dataclass

POINTS_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 17, 20]

REVEAL_GROUPS = [
    [1, 2, 3, 4, 5, 6, 7, 8, 10, 12],
    [14],
    [17],
    [20],
]


@dataclass(frozen=True)
class ScoreboardGeometryConfig:
    """Single source of truth for scoreboard animation geometry."""

    scoreboard_columns: int = 4
    rows_per_column: int = 10

    wrapper_padding_left_px: int = 16
    wrapper_padding_right_px: int = 24
    grid_gap_px: int = 22

    row_height_px: int = 52
    row_gap_px: int = 11
    rank_column_width_px: int = 36
    flag_track_width_px: int = 70
    points_box_width_px: int = 58
    pad_height_px: int = 37
    flag_width_px: int = 50
    flag_height_px: int = 37

    point_first_row_count: int = 7
    point_bubble_size_px: int = 29
    point_column_gap_px: int = 8
    point_row_gap_px: int = 10

    flying_ball_size_px: int = 38
    country_landing_x_ratio: float = 0.72
    country_landing_y_ratio: float = 0.50

    point_viewport_fallback_x_ratio: float = 0.89
    point_viewport_fallback_y_ratio: float = 0.86
    country_viewport_fallback_x_ratio: float = 0.18
    country_viewport_fallback_y_ratio: float = 0.38

    @property
    def row_step_px(self) -> int:
        return self.row_height_px + self.row_gap_px

    @property
    def column_translation_extra_px(self) -> int:
        return self.rank_column_width_px + self.grid_gap_px

    @property
    def point_center_offset_px(self) -> float:
        return self.point_bubble_size_px / 2

    @property
    def point_column_step_px(self) -> int:
        return self.point_bubble_size_px + self.point_column_gap_px

    @property
    def point_row_step_px(self) -> int:
        return self.point_bubble_size_px + self.point_row_gap_px


@dataclass(frozen=True)
class AnimationConfig:
    """Central timing settings for the live score reveal animation."""

    ball_flight_ms: int = 2100
    ball_stagger_ms: int = 700
    ball_after_pad_ms: int = 80
    row_slide_ms: int = 1050
    ball_launch_delay_ms: int = 80
    badge_early_offset_ms: int = 80
    button_lock_buffer_ms: int = 220
    point_bubble_hide_ms: int = 190
    fly_layer_cleanup_buffer_ms: int = 900


GEOMETRY = ScoreboardGeometryConfig()
ANIMATION = AnimationConfig()
