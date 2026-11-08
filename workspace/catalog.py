"""event -> catalog action string, driven by catalog/actions.json (owned by the catalog designer)."""
import json
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "catalog" / "action_tags.json"
_MAP = {}
_MTIME = 0.0


def _load():
    global _MAP, _MTIME
    m = _FILE.stat().st_mtime
    if m != _MTIME:  # hot-reload when the catalog file is edited
        _MAP = {k: v for k, v in json.loads(_FILE.read_text()).items() if not k.startswith("_")}
        _MTIME = m
    return _MAP


def to_catalog(event: dict) -> str:
    action = event["action"]
    key = _load().get(action)
    if not key:
        return action
    keys = key if isinstance(key, list) else [key]
    ctx = event.get("ctx", {})
    parts = [str(ctx[k]) for k in keys if ctx.get(k) is not None]
    return action + (":" + ":".join(parts) if parts else "")
