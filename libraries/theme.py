from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class ThemeDefinition:
    theme_id: str
    display_name: str
    primary: str
    accent: str
    background: str


THEMES = {
    "default": ThemeDefinition("default", "默认", "#5c6cff", "#eef0ff", "#ffffff"),
    "mizuki": ThemeDefinition("mizuki", "瑞希", "#d86b98", "#fff0f6", "#fff8fb"),
}


class ThemeService:
    """User theme preferences stored below the bot working directory."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.getenv("LXNS_B50_THEME_PATH", "data/lxns_b50/user_themes.json"))

    def list_themes(self) -> list[ThemeDefinition]:
        return list(THEMES.values())

    def get(self, canonical_user_id: int | str | None) -> ThemeDefinition:
        if canonical_user_id is None:
            return THEMES["default"]
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, ValueError):
            data = {}
        return THEMES.get(str(data.get(str(canonical_user_id), "default")), THEMES["default"])

    def set(self, canonical_user_id: int | str | None, theme_id: str) -> ThemeDefinition:
        if canonical_user_id is None:
            raise ValueError("canonical user identity is required")
        if theme_id not in THEMES:
            raise ValueError(f"unknown theme: {theme_id}")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, ValueError):
            data = {}
        data[str(canonical_user_id)] = theme_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            temp_name = tmp.name
        os.replace(temp_name, self.path)
        return THEMES[theme_id]
