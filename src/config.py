"""Configuration loader for habit tracker."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class HabitConfig:
    """Configuration for a single habit."""

    name: str
    notion_property: str
    icon: str
    start_date: Optional[date] = None
    deactivated_date: Optional[date] = None

    def is_active_on(self, target_date: date) -> bool:
        """Check if this habit was active on the given date."""
        if self.start_date and target_date < self.start_date:
            return False
        if self.deactivated_date and target_date >= self.deactivated_date:
            return False
        return True


@dataclass
class NotionConfig:
    """Notion API configuration."""

    api_key: str
    database_id: str
    habits_database_id: Optional[str] = None


@dataclass
class DisplayConfig:
    """Display configuration."""

    rotation: int = 0


@dataclass
class StreakConfig:
    """Streak tracking configuration."""

    enabled: bool = True


@dataclass
class CalendarConfig:
    """Calendar view configuration."""

    enabled: bool = True
    weeks: int = 12  # Number of weeks to display


@dataclass
class Config:
    """Main configuration container."""

    notion: NotionConfig
    habits: list[HabitConfig]
    display: DisplayConfig
    streak: StreakConfig
    calendar: CalendarConfig

    @property
    def has_dynamic_habits(self) -> bool:
        """Whether habits are fetched from Notion instead of config."""
        return self.notion.habits_database_id is not None


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. Defaults to config.yaml in project root.

    Returns:
        Parsed configuration object.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config is invalid.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Copy config.example.yaml to config.yaml and fill in your credentials."
        )

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("Config file is empty")

    notion_data = data.get("notion", {})
    if not notion_data.get("api_key") or not notion_data.get("database_id"):
        raise ValueError("Missing required Notion configuration (api_key, database_id)")

    notion = NotionConfig(
        api_key=notion_data["api_key"],
        database_id=notion_data["database_id"],
        habits_database_id=notion_data.get("habits_database_id"),
    )

    habits_data = data.get("habits", [])
    if not habits_data and not notion.habits_database_id:
        raise ValueError(
            "No habits configured. Either define habits in config.yaml "
            "or set notion.habits_database_id to fetch them from Notion."
        )

    habits = [
        HabitConfig(
            name=h["name"],
            notion_property=h["notion_property"],
            icon=h["icon"],
        )
        for h in habits_data
    ]

    display_data = data.get("display", {})
    display = DisplayConfig(rotation=display_data.get("rotation", 0))

    streak_data = data.get("streak", {})
    streak = StreakConfig(enabled=streak_data.get("enabled", True))

    calendar_data = data.get("calendar", {})
    calendar = CalendarConfig(
        enabled=calendar_data.get("enabled", True),
        weeks=calendar_data.get("weeks", 12),
    )

    return Config(
        notion=notion,
        habits=habits,
        display=display,
        streak=streak,
        calendar=calendar,
    )
