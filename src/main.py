#!/usr/bin/env python3
"""Habit Tracker ePaper Display - Main Entry Point.

Fetches habits from Notion and displays them on Waveshare 7.5" ePaper.
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from .config import load_config
from .display_driver import get_display_driver
from .notion_service import DayData, DaySummary, HabitStatus, NotionService
from .renderer import HabitRenderer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_demo_data() -> tuple[DayData, int, list[DaySummary]]:
    """Create demo data for preview mode without Notion.

    Returns:
        Tuple of (DayData, streak_count, history).
    """
    import random

    habits = [
        HabitStatus(name="DRINK 4L WATER", icon="water", completed=False),
        HabitStatus(name="PLAY CHESS", icon="chess", completed=True),
        HabitStatus(name="WRITE NOTES", icon="notes", completed=True),
        HabitStatus(name="BUDDY EXERCISE", icon="dog", completed=True),
        HabitStatus(name="EXERCISE", icon="exercise", completed=False),
        HabitStatus(name="READ", icon="book", completed=True),
    ]

    completed_count = sum(1 for h in habits if h.completed)
    total_habits = len(habits)

    day_data = DayData(
        date=date.today(),
        habits=habits,
        completed_count=completed_count,
        total_count=total_habits,
    )

    # Generate demo data for current month (1st through today)
    # Use a fixed seed for reproducible demo data
    random.seed(42)
    history: list[DaySummary] = []
    end_date = date.today()
    start_date = end_date.replace(day=1)  # First of current month
    total_days = (end_date - start_date).days + 1

    current = start_date
    while current <= end_date:
        # Generate realistic-looking completion patterns
        day_of_week = current.weekday()
        days_ago = (end_date - current).days

        # Base probability increases for more recent days
        base_prob = 0.5 + (0.3 * (1 - days_ago / max(total_days, 1)))

        # Weekends slightly lower completion
        if day_of_week >= 5:
            base_prob *= 0.7

        # Generate completed count with some variance
        if random.random() < 0.1:
            # Some days are 0 (missed entirely)
            completed = 0
        elif random.random() < 0.25:
            # Some days are fully complete
            completed = total_habits
        else:
            # Most days are partial
            completed = int(base_prob * total_habits + random.randint(-1, 2))
            completed = max(0, min(total_habits, completed))

        history.append(DaySummary(
            date=current,
            completed_count=completed,
            total_count=total_habits,
        ))
        current += timedelta(days=1)

    return day_data, 7, history  # Demo streak of 7 days


def run_preview(output_path: Path, use_demo: bool = False) -> None:
    """Run in preview mode - render to PNG file.

    Args:
        output_path: Path to save the preview PNG.
        use_demo: Use demo data instead of fetching from Notion.
    """
    logger.info("Running in preview mode")

    renderer = HabitRenderer()
    history: list[DaySummary] | None = None

    if use_demo:
        logger.info("Using demo data")
        day_data, streak, history = create_demo_data()
    else:
        logger.info("Fetching data from Notion")
        config = load_config()
        notion = NotionService(config)
        if config.has_dynamic_habits:
            notion.fetch_habit_configs()
        day_data = notion.get_today()
        streak = notion.calculate_streak() if config.streak.enabled else 0

        # Fetch current month data for calendar view if enabled
        if getattr(config, "calendar", None) and config.calendar.enabled:
            end_date = date.today()
            start_date = end_date.replace(day=1)  # First of current month
            logger.info(f"Fetching current month data for calendar view ({start_date} to {end_date})")
            history = notion.get_date_range(start_date, end_date)

    logger.info(
        f"Rendering: {day_data.completed_count}/{day_data.total_count} habits, "
        f"streak: {streak}"
    )

    image = renderer.render(day_data, streak, history=history)
    renderer.save_preview(image, output_path)

    logger.info(f"Preview saved to: {output_path}")


def run_display(force: bool = False) -> None:
    """Run full pipeline - fetch from Notion and display on ePaper.

    Args:
        force: Skip the change-detection check and always update.
    """
    logger.info("Running habit tracker display update")

    # Load configuration
    config = load_config()

    # Initialize services
    notion = NotionService(config)

    # Check if anything has changed before doing the expensive work
    if not force and not notion.has_changes():
        logger.info("Skipping display update — no changes in Notion")
        return

    # Fetch dynamic habits from Notion if configured
    if config.has_dynamic_habits:
        notion.fetch_habit_configs()

    renderer = HabitRenderer()
    display = get_display_driver(rotation=config.display.rotation)

    # Fetch data
    logger.info("Fetching habit data from Notion")
    day_data = notion.get_today()
    streak = notion.calculate_streak() if config.streak.enabled else 0

    # Fetch current month data for calendar view if enabled
    history: list[DaySummary] | None = None
    if getattr(config, "calendar", None) and config.calendar.enabled:
        end_date = date.today()
        start_date = end_date.replace(day=1)  # First of current month
        logger.info(f"Fetching current month data for calendar view ({start_date} to {end_date})")
        history = notion.get_date_range(start_date, end_date)

    logger.info(
        f"Today: {day_data.completed_count}/{day_data.total_count} habits completed, "
        f"streak: {streak} days"
    )

    # Render image
    logger.info("Rendering display image")
    image = renderer.render(day_data, streak, history=history)

    # Display on ePaper
    if display.init():
        try:
            logger.info("Updating ePaper display")
            display.display(image)
            display.sleep()
        finally:
            display.cleanup()
    else:
        # Fall back to saving preview if display unavailable
        preview_path = Path("preview.png")
        renderer.save_preview(image, preview_path)
        logger.info(f"Display unavailable, saved preview to: {preview_path}")

    # Save the timestamp so the next run can detect changes
    notion.save_last_edited()


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        description="Habit Tracker ePaper Display",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update ePaper display with Notion data
  python -m src.main

  # Generate preview PNG with Notion data
  python -m src.main --preview

  # Generate preview PNG with demo data (no Notion required)
  python -m src.main --preview --demo

  # Specify custom preview output path
  python -m src.main --preview --output my_preview.png
        """,
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate preview PNG instead of updating display",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use demo data instead of fetching from Notion",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("preview.png"),
        help="Output path for preview image (default: preview.png)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force display update even if Notion data hasn't changed",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        if args.demo and not args.preview:
            # Demo mode without --preview: render demo data to the ePaper display
            logger.info("Running demo data on ePaper display")
            renderer = HabitRenderer()
            day_data, streak, history = create_demo_data()
            image = renderer.render(day_data, streak, history=history)
            display = get_display_driver(rotation=0)
            if display.init():
                try:
                    logger.info("Sending demo image to ePaper display")
                    display.display(image)
                    display.sleep()
                finally:
                    display.cleanup()
            else:
                logger.warning("Display not available, saving preview instead")
                renderer.save_preview(image, args.output)
        elif args.preview:
            run_preview(args.output, use_demo=args.demo)
        else:
            run_display(force=args.force)
        return 0
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
