import json
import os
from typing import Any

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config not found at {CONFIG_PATH}. Copy config/settings.json and fill in your API keys.")
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict) -> None:
    key = cfg.get("api", {}).get("key", "")
    secret = cfg.get("api", {}).get("secret", "")
    if not key or key.startswith("YOUR_"):
        raise ValueError("API key not set. Edit config/settings.json and add your Alpaca API key.")
    if not secret or secret.startswith("YOUR_"):
        raise ValueError("API secret not set. Edit config/settings.json and add your Alpaca secret key.")


def get(cfg: dict, *keys: str, default: Any = None) -> Any:
    """Safe nested key access: get(cfg, 'risk', 'stop_loss_pct', default=2.0)"""
    val = cfg
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val
