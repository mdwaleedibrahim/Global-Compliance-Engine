"""Helper for loading limitchecker.ini configuration."""

import os
from pathlib import Path
from typing import Dict, Any, Optional


class LimitCheckerConfig:
    """Configuration loader for limitchecker.ini."""

    def __init__(self, ini_path: Optional[str] = None):
        self.ini_path = ini_path or "config/limitchecker.ini"
        self.settings: Dict[str, str] = {
            "lpt_xsession1": "last",
            "lpt_xsession2": "last",
            "lpt_xsession3": "last",
            "invalid_close_price_action": "ignore",
            "invalid_last_price_action": "ignore",
            "invalid_bbo_price_action": "reject",
        }
        self.load()

    def load(self, ini_path: Optional[str] = None) -> None:
        """Load settings from INI file."""
        target_path = ini_path or self.ini_path
        path = Path(target_path)

        if not path.exists():
            if Path("config/limitchecker.ini").exists():
                path = Path("config/limitchecker.ini")
            elif Path("limitchecker.ini").exists():
                path = Path("limitchecker.ini")
            else:
                return

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str or line_str.startswith(";") or line_str.startswith("#") or line_str.startswith("["):
                        continue
                    if "=" in line_str:
                        k, v = line_str.split("=", 1)
                        key = k.strip().lower()
                        val = v.strip().lower()
                        self.settings[key] = val
        except Exception:
            pass

    def get(self, key: str, default: str = "") -> str:
        """Get config setting value by key."""
        return self.settings.get(key.lower(), default)
