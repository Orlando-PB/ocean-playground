"""Loader for the preset JSON files: glider_playground/plot_presets.json (the app's name and
colour palettes, shared by every platform) and each platform's own presets file (plot presets
and dashboard views, see platforms/). The backend uses them for the default-plot prewarm
(cache_logic) and the 3D track colours; pages get them as a blocking script from
/api/plot_presets.js so they're available synchronously at first paint."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "plot_presets.json"

_cache = {}  # path -> (mtime, parsed config)


def load_json(path: Path, empty: dict) -> dict:
    """Parsed JSON file minus its _help block, re-read only when the file changes. A broken
    file keeps serving the last good copy (or ``empty``) rather than taking the app down."""
    mtime, cfg = _cache.get(path, (None, None))
    try:
        new_mtime = path.stat().st_mtime
        if cfg is None or new_mtime != mtime:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg.pop("_help", None)
            _cache[path] = (new_mtime, cfg)
    except Exception as e:
        print(f"[presets] could not load {path.name}: {e}")
        if cfg is None:
            cfg = empty
            _cache[path] = (None, cfg)
    return cfg


def load() -> dict:
    return load_json(CONFIG_PATH, empty={"app": {}, "palettes": {}})


def _candidates(cfg: dict, spec) -> list:
    """An x/y/c entry is either a list of names or the name of a shared 'axes' list."""
    if isinstance(spec, str):
        return list(cfg.get("axes", {}).get(spec, [spec]))
    return list(spec or [])


def prewarm_candidates(cfg: dict) -> list:
    """[(x_candidates, y_candidates, c_candidates), ...] for every preset in a platform's
    presets ``cfg`` with prewarm: true."""
    return [
        (_candidates(cfg, p.get("x")), _candidates(cfg, p.get("y")), _candidates(cfg, p.get("c")))
        for p in cfg.get("presets", {}).values()
        if p.get("prewarm")
    ]


def app_name() -> str:
    """The name shown to users ('app.name' in plot_presets.json)."""
    return load().get("app", {}).get("name") or "Ocean Playground"


def site_url() -> str:
    return (load().get("app", {}).get("site_url") or "https://glider-playground.co.uk").rstrip("/")


def as_script(platform_presets: dict, default_platform: str) -> str:
    """``platform_presets``: {platform name: its presets}. The default platform's are also at the top
    level, for pages that don't care which platform a file is."""
    cfg = {
        **load(),
        **platform_presets[default_platform],
        "platforms": platform_presets,
        "default_platform": default_platform,
    }
    return (
        "window.GP_PLOT_PRESETS = "
        + json.dumps(cfg, separators=(",", ":"))
        + ";"
        + "window.GP_APP_NAME = "
        + json.dumps(app_name())
        + ";"
    )
