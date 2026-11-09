"""Platform modules: one per kind of platform (OG1 glider/ALR, ...). Each says which files are
its own, which variables to derive for them and which plot presets and views to show.

To add one: subclass base.Platform in a new module next to og1.py, give it a presets file, and
add it to PLATFORMS ahead of og1 (which claims anything left over)."""

from pathlib import Path

import xarray as xr

from ..core import plot_logic
from .argo import Argo
from .base import Platform
from .og1 import OG1
from .saildrone import Saildrone

DEFAULT = OG1()
PLATFORMS = [Saildrone(), Argo(), DEFAULT]  # asked in order; the first to claim a file wins
_BY_NAME = {p.name: p for p in PLATFORMS}


def get(name: str) -> Platform:
    return _BY_NAME.get(name, DEFAULT)


def of(rec: dict) -> Platform:
    """The platform of a cache record (DEFAULT for records that predate the field)."""
    return get(rec.get("platform", ""))


def detect(path: str) -> tuple:
    """(platform, icon kind) from the file's global attributes. Cheap: attrs only, no data read."""
    try:
        with plot_logic.NETCDF_LOCK, xr.open_dataset(path, decode_times=False, decode_cf=False) as ds:
            attrs = {str(k).lower(): str(v) for k, v in ds.attrs.items()}
    except Exception:
        return DEFAULT, ""
    filename = Path(path).name
    for platform in PLATFORMS:
        kind = platform.detect(attrs, filename)
        if kind is not None:
            return platform, kind
    return DEFAULT, ""


def normalise(path: str, platform: Platform = None):
    """Rewrite a file we own (a download or an upload) in place into the names the app reads. Holds the app's
    netCDF lock: HDF5 isn't thread-safe, and other files are being processed on other threads meanwhile."""
    with plot_logic.NETCDF_LOCK:
        (platform or detect(path)[0]).normalise(path)
