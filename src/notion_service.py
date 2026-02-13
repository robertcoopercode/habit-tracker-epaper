"""Notion API service for fetching habit data."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx
from notion_client import Client

from .config import Config, HabitConfig

logger = logging.getLogger(__name__)

# Path to store last-seen database edit timestamp
LAST_EDIT_FILE = ".last_notion_edit"


@dataclass
class HabitStatus:
    """Status of a single habit for a day."""

    name: str
    icon: str
    completed: bool


@dataclass
class DayData:
    """All habit data for a single day."""

    date: date
    habits: list[HabitStatus]
    completed_count: int
    total_count: int

    @property
    def all_completed(self) -> bool:
        """Check if all habits are completed."""
        return self.completed_count == self.total_count


@dataclass
class DaySummary:
    """Summary of habit completion for a single day (used for calendar view)."""

    date: date
    completed_count: int
    total_count: int

    @property
    def completion_ratio(self) -> float:
        """Get completion ratio as a float between 0 and 1."""
        return self.completed_count / self.total_count if self.total_count > 0 else 0

    @property
    def all_completed(self) -> bool:
        """Check if all habits are completed."""
        return self.completed_count == self.total_count


class NotionService:
    """Service for interacting with Notion habit database."""

    def __init__(self, config: Config):
        """Initialize Notion service.

        Args:
            config: Application configuration.
        """
        self.config = config
        self.client = Client(auth=config.notion.api_key)
        self.database_id = self._format_uuid(config.notion.database_id)

    @staticmethod
    def _format_uuid(id_str: str) -> str:
        """Format a string as a UUID with dashes if needed.

        Args:
            id_str: ID string, possibly without dashes.

        Returns:
            UUID-formatted string with dashes.
        """
        # Remove any existing dashes and spaces
        clean = id_str.replace("-", "").replace(" ", "")

        # If it's 32 chars, format as UUID
        if len(clean) == 32:
            return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"

        # Otherwise return as-is
        return id_str

    def fetch_habit_configs(self) -> list[HabitConfig]:
        """Fetch all habit definitions from the Habits Notion database.

        Queries the habits metadata database sorted by Sort order.
        Habits with a Deactivated date are included so they can still
        be used in historical calculations. Updates self.config.habits
        in place.

        Returns:
            List of HabitConfig objects.
        """
        habits_db_id = self.config.notion.habits_database_id
        if not habits_db_id:
            logger.debug("No habits_database_id configured, using config.yaml habits")
            return self.config.habits

        habits_db_id = self._format_uuid(habits_db_id)
        logger.info("Fetching habit definitions from Notion")

        url = f"https://api.notion.com/v1/databases/{habits_db_id}/query"
        headers = {
            "Authorization": f"Bearer {self.config.notion.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        body = {
            "sorts": [
                {"property": "Sort order", "direction": "ascending"},
            ],
        }

        response = httpx.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json().get("results", [])

        habits = []
        for page in results:
            props = page.get("properties", {})

            # Name (title) = the Notion property name in the tracking database
            name_prop = props.get("Name", {})
            title_parts = name_prop.get("title", [])
            notion_property = title_parts[0]["plain_text"] if title_parts else ""

            # Display (rich_text) = what shows on the ePaper screen
            display_prop = props.get("Display", {})
            display_parts = display_prop.get("rich_text", [])
            display_name = display_parts[0]["plain_text"] if display_parts else notion_property.upper()

            # Icon (rich_text) = icon filename
            icon_prop = props.get("Icon", {})
            icon_parts = icon_prop.get("rich_text", [])
            icon = icon_parts[0]["plain_text"] if icon_parts else ""

            # Start date (date) = when tracking began
            start_date_val = None
            start_prop = props.get("Start date", {})
            if start_prop.get("type") == "date" and start_prop.get("date"):
                start_str = start_prop["date"].get("start")
                if start_str:
                    start_date_val = date.fromisoformat(start_str)

            # Deactivated (date) = when habit was retired
            deactivated_val = None
            deact_prop = props.get("Deactivated", {})
            if deact_prop.get("type") == "date" and deact_prop.get("date"):
                deact_str = deact_prop["date"].get("start")
                if deact_str:
                    deactivated_val = date.fromisoformat(deact_str)

            if notion_property:
                habits.append(HabitConfig(
                    name=display_name,
                    notion_property=notion_property,
                    icon=icon,
                    start_date=start_date_val,
                    deactivated_date=deactivated_val,
                ))

        active_count = sum(1 for h in habits if h.is_active_on(date.today()))
        logger.info(f"Loaded {len(habits)} habits ({active_count} active today)")
        self.config.habits = habits
        return habits

    def _query_database(self, filter_obj: Optional[dict] = None) -> dict:
        """Query the Notion database.

        Args:
            filter_obj: Optional filter to apply.

        Returns:
            Query response dict.
        """
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        headers = {
            "Authorization": f"Bearer {self.config.notion.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        body = {}
        if filter_obj:
            body["filter"] = filter_obj

        response = httpx.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()

    def _get_latest_edit_time(self, database_id: str) -> str:
        """Get the most recent page edit time in a database.

        Queries for the single most recently edited page and returns
        its last_edited_time. This detects actual data changes, unlike
        databases.retrieve which only reflects schema changes.

        Args:
            database_id: The database to check.

        Returns:
            ISO timestamp of the most recently edited page,
            or empty string if the database has no pages.
        """
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        headers = {
            "Authorization": f"Bearer {self.config.notion.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        body = {
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            "page_size": 1,
        }
        response = httpx.post(url, headers=headers, json=body)
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0]["last_edited_time"] if results else ""

    def has_changes(self) -> bool:
        """Check if any tracked database has been modified since we last looked.

        Queries each database for its most recently edited page and
        compares against locally stored timestamps.

        Returns:
            True if any database has changed (or if this is the first check).
        """
        state_file = Path(LAST_EDIT_FILE)

        timestamps = [self._get_latest_edit_time(self.database_id)]

        habits_db_id = self.config.notion.habits_database_id
        if habits_db_id:
            timestamps.append(
                self._get_latest_edit_time(self._format_uuid(habits_db_id))
            )

        current = "|".join(timestamps)

        if state_file.exists():
            previous = state_file.read_text().strip()
            if current == previous:
                logger.info(f"No changes (timestamps={current})")
                return False

        self._combined_timestamp = current
        logger.info(f"Changes detected (timestamps={current})")
        return True

    def save_last_edited(self) -> None:
        """Save the last-seen database timestamps to disk.

        Call this after a successful display update so the next
        has_changes() check can compare against it.
        """
        ts = getattr(self, "_combined_timestamp", None)
        if not ts:
            # Fetch if has_changes() wasn't called (e.g. --force)
            timestamps = [self._get_latest_edit_time(self.database_id)]
            habits_db_id = self.config.notion.habits_database_id
            if habits_db_id:
                timestamps.append(
                    self._get_latest_edit_time(self._format_uuid(habits_db_id))
                )
            ts = "|".join(timestamps)
        Path(LAST_EDIT_FILE).write_text(ts)

    def verify_connection(self) -> bool:
        """Verify the database is accessible.

        Returns:
            True if database is accessible.

        Raises:
            Exception with helpful message if not accessible.
        """
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            print(f"Connected to database: {db.get('title', [{}])[0].get('plain_text', 'Untitled')}")
            return True
        except Exception as e:
            raise Exception(
                f"Cannot access database. Make sure:\n"
                f"1. The database ID is correct (from the URL)\n"
                f"2. You've shared the database with your integration\n"
                f"   (Click '...' menu > 'Connect to' > select your integration)\n"
                f"Original error: {e}"
            )

    def _get_page_for_date(self, target_date: date) -> Optional[dict]:
        """Find the Notion page for a specific date.

        Args:
            target_date: The date to find.

        Returns:
            The page dict if found, None otherwise.
        """
        date_str = target_date.isoformat()

        response = self._query_database(
            filter_obj={
                "property": "Date",
                "date": {"equals": date_str},
            }
        )

        results = response.get("results", [])
        return results[0] if results else None

    def _parse_habit_status(
        self, page: dict, habit_config: HabitConfig
    ) -> HabitStatus:
        """Parse habit completion status from a page.

        Args:
            page: Notion page data.
            habit_config: Configuration for the habit.

        Returns:
            HabitStatus with completion info.
        """
        properties = page.get("properties", {})
        prop = properties.get(habit_config.notion_property, {})

        # Handle checkbox type
        if prop.get("type") == "checkbox":
            completed = prop.get("checkbox", False)
        # Handle number type (for water tracking, etc.)
        elif prop.get("type") == "number":
            value = prop.get("number", 0) or 0
            # Consider it complete if there's any value > 0
            # You could customize this threshold per habit
            completed = value > 0
        # Handle select type
        elif prop.get("type") == "select":
            select = prop.get("select")
            completed = select is not None
        else:
            # Default to not completed for unknown types
            completed = False

        return HabitStatus(
            name=habit_config.name,
            icon=habit_config.icon,
            completed=completed,
        )

    def get_today(self) -> DayData:
        """Get habit data for today.

        Returns:
            DayData with today's habits.
        """
        return self.get_day(date.today())

    def get_day(self, target_date: date) -> DayData:
        """Get habit data for a specific date.

        Only includes habits that were active on the target date
        (based on their start_date and deactivated_date).

        Args:
            target_date: The date to fetch.

        Returns:
            DayData with habit information.
        """
        page = self._get_page_for_date(target_date)

        # Filter to habits that were active on this date
        active_habits = [h for h in self.config.habits if h.is_active_on(target_date)]

        habits = []
        for habit_config in active_habits:
            if page:
                status = self._parse_habit_status(page, habit_config)
            else:
                # No page for this date, all habits incomplete
                status = HabitStatus(
                    name=habit_config.name,
                    icon=habit_config.icon,
                    completed=False,
                )
            habits.append(status)

        completed_count = sum(1 for h in habits if h.completed)

        return DayData(
            date=target_date,
            habits=habits,
            completed_count=completed_count,
            total_count=len(habits),
        )

    def get_date_range(self, start_date: date, end_date: date) -> list[DaySummary]:
        """Fetch summary data for a date range in a single API call.

        Args:
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).

        Returns:
            List of DaySummary objects for each day in the range.
        """
        # Query all pages in the date range with a single API call
        response = self._query_database(
            filter_obj={
                "and": [
                    {"property": "Date", "date": {"on_or_after": start_date.isoformat()}},
                    {"property": "Date", "date": {"on_or_before": end_date.isoformat()}},
                ]
            }
        )

        # Build a dict of date -> page for quick lookup
        pages_by_date: dict[date, dict] = {}
        for page in response.get("results", []):
            props = page.get("properties", {})
            date_prop = props.get("Date", {})
            if date_prop.get("type") == "date" and date_prop.get("date"):
                page_date_str = date_prop["date"].get("start")
                if page_date_str:
                    page_date = date.fromisoformat(page_date_str)
                    pages_by_date[page_date] = page

        # Build summaries for each day in the range
        summaries: list[DaySummary] = []
        current = start_date

        while current <= end_date:
            page = pages_by_date.get(current)

            # Filter to habits that were active on this specific day
            active_habits = [h for h in self.config.habits if h.is_active_on(current)]
            total_habits = len(active_habits)

            if page and total_habits > 0:
                # Count completed habits from the page
                completed = sum(
                    1 for hc in active_habits
                    if self._parse_habit_status(page, hc).completed
                )
                summaries.append(DaySummary(
                    date=current,
                    completed_count=completed,
                    total_count=total_habits,
                ))
            else:
                # No page for this date or no active habits
                summaries.append(DaySummary(
                    date=current,
                    completed_count=0,
                    total_count=total_habits,
                ))

            current += timedelta(days=1)

        return summaries

    def calculate_streak(self, from_date: Optional[date] = None) -> int:
        """Calculate current streak of days with all habits completed.

        Args:
            from_date: Date to start counting back from. Defaults to today.

        Returns:
            Number of consecutive days with all habits completed.
        """
        if from_date is None:
            from_date = date.today()

        streak = 0
        current_date = from_date

        # Check up to 365 days back (reasonable limit)
        for _ in range(365):
            day_data = self.get_day(current_date)

            if day_data.all_completed:
                streak += 1
                current_date -= timedelta(days=1)
            else:
                # If today isn't complete yet, check if yesterday starts a streak
                if current_date == from_date and streak == 0:
                    current_date -= timedelta(days=1)
                    continue
                break

        return streak
