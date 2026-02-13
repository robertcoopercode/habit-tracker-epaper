"""Pillow-based renderer for habit tracker display."""

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .notion_service import DayData, DaySummary

# Display dimensions for Waveshare 7.5" V2
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Colors (1-bit: 0=black, 1=white for the image mode we use)
BLACK = 0
WHITE = 1

# Layout constants
MARGIN = 20
HEADER_HEIGHT = 60
FOOTER_HEIGHT = 80
HABIT_ROW_HEIGHT = 50
ICON_SIZE = 32

# Calendar layout constants
CALENDAR_WIDTH = 340  # Width of calendar section
DIVIDER_X = CALENDAR_WIDTH + MARGIN  # X position of vertical divider
HABITS_AREA_X = DIVIDER_X + 10  # Start of habits area

# Monthly calendar grid constants
CALENDAR_CELL_SIZE = 30  # Size of each day cell (larger for better visibility)
CALENDAR_CELL_GAP = 4  # Gap between cells
CALENDAR_COLS = 7  # Days per week (Sun-Sat)
CALENDAR_MARGIN_TOP = 110  # Space for header and month title (with top margin)


class HabitRenderer:
    """Renders habit data to an image for ePaper display."""

    def __init__(self, assets_path: Path | None = None):
        """Initialize renderer.

        Args:
            assets_path: Path to assets directory. Defaults to ../assets relative to this file.
        """
        if assets_path is None:
            assets_path = Path(__file__).parent.parent / "assets"

        self.assets_path = assets_path
        self.fonts_path = assets_path / "fonts"
        self.icons_path = assets_path / "icons"

        # Load fonts
        self._load_fonts()

        # Cache for loaded icons
        self._icon_cache: dict[str, Image.Image] = {}

    def _load_fonts(self) -> None:
        """Load pixel fonts for rendering."""
        font_path = self.fonts_path / "PressStart2P.ttf"

        if not font_path.exists():
            raise FileNotFoundError(f"Font not found: {font_path}")

        # Different sizes for different elements
        self.font_title = ImageFont.truetype(str(font_path), 16)
        self.font_date = ImageFont.truetype(str(font_path), 12)
        self.font_habit = ImageFont.truetype(str(font_path), 12)
        self.font_progress = ImageFont.truetype(str(font_path), 10)
        self.font_streak = ImageFont.truetype(str(font_path), 10)
        self.font_calendar = ImageFont.truetype(str(font_path), 8)  # Small font for calendar labels
        self.font_calendar_title = ImageFont.truetype(str(font_path), 10)  # Calendar section title

    def _load_icon(self, icon_name: str) -> Image.Image:
        """Load and cache an icon.

        Args:
            icon_name: Name of the icon (without extension).

        Returns:
            PIL Image of the icon, resized to ICON_SIZE.
        """
        if icon_name in self._icon_cache:
            return self._icon_cache[icon_name]

        icon_path = self.icons_path / f"{icon_name}.png"

        if icon_path.exists():
            icon = Image.open(icon_path).convert("1")
            icon = icon.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.NEAREST)
        else:
            # Create a placeholder icon
            icon = Image.new("1", (ICON_SIZE, ICON_SIZE), WHITE)
            draw = ImageDraw.Draw(icon)
            draw.rectangle([2, 2, ICON_SIZE - 3, ICON_SIZE - 3], outline=BLACK)

        self._icon_cache[icon_name] = icon
        return icon

    def _draw_cell_pattern(
        self, draw: ImageDraw.ImageDraw, x: int, y: int, size: int, completion_ratio: float
    ) -> None:
        """Draw a calendar cell with fill pattern based on completion.

        Patterns:
        - 0%: Empty square (outline only)
        - 1-49%: Sparse diagonal lines (hatching)
        - 50-99%: Dense crosshatch pattern
        - 100%: Solid black fill

        Args:
            draw: ImageDraw object.
            x: X position of cell.
            y: Y position of cell.
            size: Size of the cell (square).
            completion_ratio: Completion ratio (0.0 to 1.0).
        """
        # Draw the cell outline
        draw.rectangle([x, y, x + size - 1, y + size - 1], outline=BLACK)

        if completion_ratio == 0:
            # Empty - just the outline (already drawn)
            pass
        elif completion_ratio < 0.5:
            # Sparse diagonal hatching (bottom-left to top-right)
            # Draw lines at 45 degrees
            for i in range(0, size * 2, 3):
                # Line from bottom-left towards top-right
                x1 = x + max(0, i - size)
                y1 = y + min(size - 1, i)
                x2 = x + min(size - 1, i)
                y2 = y + max(0, i - size)
                if x1 < x + size and y2 < y + size:
                    draw.line([(x1, y1), (x2, y2)], fill=BLACK)
        elif completion_ratio < 1.0:
            # Dense crosshatch pattern
            # Diagonal lines in both directions
            for i in range(0, size * 2, 2):
                # Bottom-left to top-right
                x1 = x + max(0, i - size)
                y1 = y + min(size - 1, i)
                x2 = x + min(size - 1, i)
                y2 = y + max(0, i - size)
                if x1 < x + size and y2 < y + size:
                    draw.line([(x1, y1), (x2, y2)], fill=BLACK)
                # Top-left to bottom-right
                x1 = x + max(0, i - size)
                y1 = y + max(0, size - 1 - i)
                x2 = x + min(size - 1, i)
                y2 = y + min(size - 1, size - 1 - (i - size))
                if x1 < x + size and y1 >= y:
                    x2_clamped = x + min(size - 1, i)
                    y2_clamped = y + size - 1 - min(size - 1, i) + max(0, i - size)
                    draw.line([(x1, y1), (x2_clamped, y2_clamped)], fill=BLACK)
        else:
            # 100% - Solid fill
            draw.rectangle([x + 1, y + 1, x + size - 2, y + size - 2], fill=BLACK)

    def _draw_calendar_grid(
        self, draw: ImageDraw.ImageDraw, history: list[DaySummary]
    ) -> None:
        """Draw the monthly calendar grid.

        Shows all days of the current month with completion pattern boxes.
        No day numbers, no empty placeholder cells before/after the month.

        Args:
            draw: ImageDraw object.
            history: List of DaySummary objects for the current month.
        """
        import calendar
        from datetime import timedelta

        today = date.today()

        # Calculate grid dimensions
        cell_step = CALENDAR_CELL_SIZE + CALENDAR_CELL_GAP
        grid_width = (CALENDAR_COLS * cell_step) - CALENDAR_CELL_GAP  # Total grid width

        # Center the grid within the calendar section
        calendar_section_center = MARGIN + (CALENDAR_WIDTH // 2)
        grid_start_x = calendar_section_center - (grid_width // 2)
        grid_start_y = CALENDAR_MARGIN_TOP + 20  # Space for title and day headers

        # Draw month title (e.g., "FEBRUARY 2026") - centered with top margin
        month_title = today.strftime("%B %Y").upper()
        title_bbox = draw.textbbox((0, 0), month_title, font=self.font_calendar_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = calendar_section_center - (title_width // 2)
        title_y = HEADER_HEIGHT + 30  # Added top margin
        draw.text((title_x, title_y), month_title, font=self.font_calendar_title, fill=BLACK)

        # Draw day-of-week headers (S M T W T F S)
        day_headers = ["S", "M", "T", "W", "T", "F", "S"]
        header_y = grid_start_y - 18
        for col, header in enumerate(day_headers):
            header_x = grid_start_x + (col * cell_step) + (CALENDAR_CELL_SIZE // 2) - 3
            draw.text((header_x, header_y), header, font=self.font_calendar, fill=BLACK)

        # Create a dict for quick lookup of completion by date
        completion_by_date: dict[date, float] = {}
        for summary in history:
            completion_by_date[summary.date] = summary.completion_ratio

        # Get first day of month and last day of month
        first_of_month = today.replace(day=1)
        # Get number of days in this month
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        last_of_month = today.replace(day=days_in_month)

        # weekday() returns 0=Monday, but we want 0=Sunday
        first_day_weekday = (first_of_month.weekday() + 1) % 7  # Convert to Sun=0

        # Iterate through all days of the month
        current_date = first_of_month
        while current_date <= last_of_month:
            # Calculate which weekday (0=Sun, 6=Sat)
            weekday = (current_date.weekday() + 1) % 7

            # Calculate week row (0-indexed)
            days_since_first = (current_date - first_of_month).days
            week_row = (first_day_weekday + days_since_first) // 7

            # Calculate cell position
            cell_x = grid_start_x + (weekday * cell_step)
            cell_y = grid_start_y + (week_row * cell_step)

            # Get completion ratio for this date (0.0 for future days)
            ratio = completion_by_date.get(current_date, 0.0)

            # Draw the cell with pattern
            self._draw_cell_pattern(draw, cell_x, cell_y, CALENDAR_CELL_SIZE, ratio)

            current_date += timedelta(days=1)

        # Calculate where legend should go (below the last week row)
        last_week_row = (first_day_weekday + days_in_month - 1) // 7
        legend_y = grid_start_y + ((last_week_row + 1) * cell_step) + 25

        # Draw legend (centered)
        legend_cell_size = 14  # Smaller cells for legend
        legend_cell_step = legend_cell_size + 4
        # Calculate total legend width: "LESS" + 4 cells + "MORE"
        less_width = 35
        more_width = 35
        cells_width = 4 * legend_cell_step
        total_legend_width = less_width + cells_width + more_width

        legend_start_x = calendar_section_center - (total_legend_width // 2)

        draw.text((legend_start_x, legend_y), "LESS", font=self.font_calendar, fill=BLACK)
        cells_start_x = legend_start_x + less_width

        # Draw 4 sample cells for legend
        for i, ratio in enumerate([0.0, 0.25, 0.75, 1.0]):
            self._draw_cell_pattern(draw, cells_start_x + (i * legend_cell_step), legend_y - 2, legend_cell_size, ratio)

        more_x = cells_start_x + cells_width
        draw.text((more_x, legend_y), "MORE", font=self.font_calendar, fill=BLACK)

    def _draw_border(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw the retro border around the display."""
        # Double-line border for retro look
        # Outer border
        draw.rectangle(
            [4, 4, DISPLAY_WIDTH - 5, DISPLAY_HEIGHT - 5],
            outline=BLACK,
            width=2,
        )
        # Inner border
        draw.rectangle(
            [10, 10, DISPLAY_WIDTH - 11, DISPLAY_HEIGHT - 11],
            outline=BLACK,
            width=1,
        )

    def _draw_header(self, draw: ImageDraw.ImageDraw, day_data: DayData) -> None:
        """Draw the header with title and date."""
        header_y = 20

        # Title: "★ DAILY QUESTS ★"
        title = "* DAILY QUESTS *"
        title_bbox = draw.textbbox((0, 0), title, font=self.font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = MARGIN + 40
        draw.text((title_x, header_y), title, font=self.font_title, fill=BLACK)

        # Date: "THU • JAN 30 • 2026"
        date_str = day_data.date.strftime("%a \u2022 %b %d \u2022 %Y").upper()
        date_bbox = draw.textbbox((0, 0), date_str, font=self.font_date)
        date_width = date_bbox[2] - date_bbox[0]
        date_x = DISPLAY_WIDTH - MARGIN - date_width - 40
        draw.text((date_x, header_y + 4), date_str, font=self.font_date, fill=BLACK)

        # Header separator line
        line_y = header_y + 40
        draw.line([(MARGIN, line_y), (DISPLAY_WIDTH - MARGIN, line_y)], fill=BLACK, width=2)

    def _draw_checkbox(
        self, draw: ImageDraw.ImageDraw, x: int, y: int, checked: bool
    ) -> None:
        """Draw a pixel-art checkbox.

        Args:
            draw: ImageDraw object.
            x: X position.
            y: Y position.
            checked: Whether the box is checked.
        """
        box_size = 28

        # Draw the box outline
        draw.rectangle([x, y, x + box_size, y + box_size], outline=BLACK, width=2)

        if checked:
            # Draw checkmark
            # Simple pixel checkmark
            check_points = [
                (x + 6, y + 14),
                (x + 11, y + 20),
                (x + 22, y + 8),
            ]
            draw.line(check_points[:2], fill=BLACK, width=3)
            draw.line(check_points[1:], fill=BLACK, width=3)

    def _draw_habit_row(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        y: int,
        icon_name: str,
        name: str,
        completed: bool,
        start_x: int | None = None,
        end_x: int | None = None,
    ) -> None:
        """Draw a single habit row.

        Args:
            image: PIL Image to paste icon onto.
            draw: ImageDraw object.
            y: Y position for the row.
            icon_name: Name of the icon to display.
            name: Habit name text.
            completed: Whether the habit is completed.
            start_x: Optional start X position (for split layout).
            end_x: Optional end X position (for split layout).
        """
        if start_x is None:
            start_x = MARGIN + 30
        if end_x is None:
            end_x = DISPLAY_WIDTH - MARGIN

        row_x = start_x
        checkbox_x = end_x - 40

        # Load and paste icon
        icon = self._load_icon(icon_name)
        icon_y = y + (HABIT_ROW_HEIGHT - ICON_SIZE) // 2
        image.paste(icon, (row_x, icon_y))

        # Draw habit name
        text_x = row_x + ICON_SIZE + 15
        text_y = y + (HABIT_ROW_HEIGHT - 12) // 2  # Center vertically
        draw.text((text_x, text_y), name, font=self.font_habit, fill=BLACK)

        # Draw checkbox
        checkbox_y = y + (HABIT_ROW_HEIGHT - 28) // 2
        self._draw_checkbox(draw, checkbox_x, checkbox_y, completed)

    def _draw_progress_bar(
        self,
        draw: ImageDraw.ImageDraw,
        y: int,
        completed: int,
        total: int,
        center_x: int | None = None,
        bar_width: int = 350,
    ) -> None:
        """Draw the progress bar.

        Args:
            draw: ImageDraw object.
            y: Y position.
            completed: Number of completed habits.
            total: Total number of habits.
            center_x: Optional center X position (for split layout).
            bar_width: Width of the progress bar.
        """
        bar_height = 16
        if center_x is None:
            center_x = DISPLAY_WIDTH // 2
        bar_x = center_x - bar_width // 2

        # Label and progress count on same line, centered
        label = "QUEST PROGRESS"
        progress_text = f"{completed}/{total} DONE"
        full_text = f"{label}  {progress_text}"
        text_bbox = draw.textbbox((0, 0), full_text, font=self.font_progress)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = center_x - text_width // 2
        draw.text((text_x, y), full_text, font=self.font_progress, fill=BLACK)

        # Bar background (below the label)
        bar_y = y + 18
        draw.rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            outline=BLACK,
            width=2,
        )

        # Filled portion
        if total > 0:
            fill_width = int((completed / total) * (bar_width - 4))
            if fill_width > 0:
                # Create pixelated fill effect
                for i in range(0, fill_width, 4):
                    segment_width = min(4, fill_width - i)
                    draw.rectangle(
                        [bar_x + 2 + i, bar_y + 2, bar_x + 2 + i + segment_width - 1, bar_y + bar_height - 2],
                        fill=BLACK,
                    )

    def _draw_streak(
        self, draw: ImageDraw.ImageDraw, y: int, streak: int, center_x: int | None = None
    ) -> None:
        """Draw the streak counter.

        Args:
            draw: ImageDraw object.
            y: Y position.
            streak: Current streak count.
            center_x: Optional center X position (for split layout).
        """
        if center_x is None:
            center_x = DISPLAY_WIDTH // 2
        streak_text = f"* STREAK: {streak} DAYS *"
        text_bbox = draw.textbbox((0, 0), streak_text, font=self.font_streak)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = center_x - text_width // 2
        draw.text((text_x, y), streak_text, font=self.font_streak, fill=BLACK)

    def _draw_footer_separator(self, draw: ImageDraw.ImageDraw, y: int) -> None:
        """Draw the separator line above the footer."""
        draw.line(
            [(MARGIN, y), (DISPLAY_WIDTH - MARGIN, y)],
            fill=BLACK,
            width=2,
        )

    def render(
        self,
        day_data: DayData,
        streak: int = 0,
        history: list[DaySummary] | None = None,
    ) -> Image.Image:
        """Render the full display image.

        Args:
            day_data: Habit data for the day.
            streak: Current streak count.
            history: Optional list of historical day summaries for calendar view.

        Returns:
            PIL Image ready for display (800x480, mode "1").
        """
        # Create white background image
        image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), WHITE)
        draw = ImageDraw.Draw(image)

        # Draw border
        self._draw_border(draw)

        # Determine if we're using split layout (with calendar)
        use_calendar = history is not None and len(history) > 0

        if use_calendar:
            # Split layout: calendar on left, habits on right
            self._render_split_layout(image, draw, day_data, streak, history)
        else:
            # Original full-width layout
            self._render_full_layout(image, draw, day_data, streak)

        return image

    def _render_full_layout(
        self, image: Image.Image, draw: ImageDraw.ImageDraw, day_data: DayData, streak: int
    ) -> None:
        """Render the original full-width layout (no calendar).

        Args:
            image: PIL Image to draw on.
            draw: ImageDraw object.
            day_data: Habit data for the day.
            streak: Current streak count.
        """
        # Draw header
        self._draw_header(draw, day_data)

        # Calculate habit area
        habits_start_y = HEADER_HEIGHT + 30
        available_height = DISPLAY_HEIGHT - habits_start_y - FOOTER_HEIGHT - 20
        num_habits = len(day_data.habits)

        # Adjust row height if needed
        row_height = min(HABIT_ROW_HEIGHT, available_height // max(num_habits, 1))

        # Draw habit rows
        for i, habit in enumerate(day_data.habits):
            row_y = habits_start_y + (i * row_height)
            self._draw_habit_row(
                image,
                draw,
                row_y,
                habit.icon,
                habit.name,
                habit.completed,
            )

        # Draw footer separator
        footer_y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        self._draw_footer_separator(draw, footer_y)

        # Draw progress bar
        progress_y = footer_y + 15
        self._draw_progress_bar(
            draw, progress_y, day_data.completed_count, day_data.total_count
        )

        # Draw streak
        streak_y = progress_y + 42
        self._draw_streak(draw, streak_y, streak)

    def _render_split_layout(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        day_data: DayData,
        streak: int,
        history: list[DaySummary],
    ) -> None:
        """Render the split layout with calendar on left and habits on right.

        Args:
            image: PIL Image to draw on.
            draw: ImageDraw object.
            day_data: Habit data for the day.
            streak: Current streak count.
            history: Historical day summaries for calendar.
        """
        # Draw header (full width)
        self._draw_header(draw, day_data)

        # Draw vertical divider
        divider_y_start = HEADER_HEIGHT + 5
        divider_y_end = DISPLAY_HEIGHT - FOOTER_HEIGHT - 5
        draw.line(
            [(DIVIDER_X, divider_y_start), (DIVIDER_X, divider_y_end)],
            fill=BLACK,
            width=2,
        )

        # Draw calendar on the left
        self._draw_calendar_grid(draw, history)

        # Draw habits on the right
        habits_start_x = HABITS_AREA_X
        habits_end_x = DISPLAY_WIDTH - MARGIN - 20
        habits_center_x = (habits_start_x + habits_end_x) // 2

        # Calculate habit area
        habits_start_y = HEADER_HEIGHT + 15
        available_height = DISPLAY_HEIGHT - habits_start_y - FOOTER_HEIGHT - 10
        num_habits = len(day_data.habits)

        # Use smaller row height for split layout
        row_height = min(HABIT_ROW_HEIGHT - 5, available_height // max(num_habits, 1))

        # Draw habit rows
        for i, habit in enumerate(day_data.habits):
            row_y = habits_start_y + (i * row_height)
            self._draw_habit_row(
                image,
                draw,
                row_y,
                habit.icon,
                habit.name,
                habit.completed,
                start_x=habits_start_x,
                end_x=habits_end_x,
            )

        # Draw footer separator (full width)
        footer_y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        self._draw_footer_separator(draw, footer_y)

        # Draw progress bar (centered across full display)
        progress_y = footer_y + 15
        self._draw_progress_bar(
            draw,
            progress_y,
            day_data.completed_count,
            day_data.total_count,
            center_x=DISPLAY_WIDTH // 2,
            bar_width=350,
        )

        # Draw streak (centered across full display)
        streak_y = progress_y + 42
        self._draw_streak(draw, streak_y, streak, center_x=DISPLAY_WIDTH // 2)

    def save_preview(self, image: Image.Image, output_path: Path) -> None:
        """Save a preview image.

        Args:
            image: Rendered image.
            output_path: Path to save the preview.
        """
        # Convert to RGB for better preview viewing
        preview = image.convert("RGB")
        preview.save(output_path)
