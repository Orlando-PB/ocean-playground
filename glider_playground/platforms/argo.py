"""Argo profiling floats, from GDAC profile files: <wmo>_prof.nc (core T/S) or <wmo>_Sprof.nc
(synthetic BGC: core plus oxygen, chlorophyll, nitrate, ...). normalise flattens a file's
N_PROF x N_LEVELS grid into the one row dimension the app reads, one row per measured level."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from ..core import derive_logic
from .base import Platform

_FILENAME = re.compile(r"^\d{7}_S?prof", re.IGNORECASE)
_SKIP_SUFFIXES = ("_dPRES", "_ADJUSTED_ERROR")  # per-level bookkeeping, not measurements
_BAD_POSITION = (b"3", b"4", b"9")
_JULD_EPOCH = -7305 * 86400.0  # 1950-01-01 in seconds since 1970-01-01
_KEEP_ATTRS = ("institution", "source", "references", "history", "user_manual_version")


class Argo(Platform):
    name = "argo"
    presets_file = Path(__file__).with_name("argo_presets.json")
    derive_steps = (
        ("TIME QC", derive_logic.compute_time_qc),
        ("CTD", derive_logic.compute_ctd_from_psal),
    )
    live_source = {
        "key": "argo",
        "title": "Argo floats",
        "credit": "Data provided by the Argo GDAC",
        "credit_full": "Argo data were collected and made freely available by the International Argo Program and the national programs that contribute to it (https://argo.ucsd.edu, https://www.ocean-ops.org). The Argo Program is part of the Global Ocean Observing System. https://doi.org/10.17882/42182",
        "url": "https://argo.ucsd.edu/data/acknowledging-argo/",
        "empty": "Open a float from its card on the map (Argo layer) to see its profiles here.",
    }

    def live_entries(self, days_active):
        """Only the floats the user opened (see maps/argo_logic.open_float), not every active one."""
        from ..maps import argo_logic  # imports the live feed, which imports this registry

        return argo_logic.live_entries()

    def detect(self, attrs, filename):
        text = " ".join(attrs.get(k, "") for k in ("title", "source", "platform_type")).lower()
        if "argo float" in text or _FILENAME.match(filename):
            return "argo"
        return None

    def normalise(self, path):
        """In place: one row per level with a valid pressure, profiles in time order and each profile's
        levels in the order they were measured. Character and calibration/history metadata are dropped."""
        tmp = path + ".argo-tmp"
        with Dataset(path) as src:
            if "N_PROF" not in src.dimensions:
                return  # already flat
            src.set_auto_mask(False)
            with Dataset(tmp, "w") as dst:
                _write_flat(src, dst)
        os.replace(tmp, path)


def _chars(var) -> list:
    """A char variable as one stripped string per profile."""
    raw = var[:]
    return [b"".join(row).decode("ascii", "replace").strip() for row in raw.reshape(raw.shape[0], -1)]


def _numeric(var, rows=None):
    """A numeric variable as float with its fill value as NaN, indexed by ``rows`` if given."""
    values = var[:] if rows is None else var[:][rows]
    values = values.astype(float)
    fill = getattr(var, "_FillValue", None)
    if fill is not None:
        values[values == fill] = np.nan
    return values


def _flags(qc_var, values, rows):
    """Argo char flags '0'-'9' as int8. A blank flag is 9 (missing) where there is no value, else 0 (no QC)."""
    chars = qc_var[:][rows]
    flags = np.zeros(chars.shape, dtype=np.int8)
    digit = (chars >= b"0") & (chars <= b"9")
    flags[digit] = chars[digit].view(np.uint8) - ord("0")
    flags[~digit & ~np.isfinite(values)] = 9
    return flags


def _write_flat(src, dst):
    juld = _numeric(src["JULD"])
    pres = _numeric(src["PRES"])
    direction = src["DIRECTION"][:]
    lat = _numeric(src["LATITUDE"])
    lon = _numeric(src["LONGITUDE"])
    bad_position = np.isin(src["POSITION_QC"][:], _BAD_POSITION)
    lat[bad_position] = np.nan
    lon[bad_position] = np.nan

    profiles = [p for p in np.argsort(juld, kind="stable") if np.isfinite(juld[p])]
    prof_rows, level_rows = [], []
    for p in profiles:
        levels = np.flatnonzero(np.isfinite(pres[p]))
        if direction[p] == b"A":
            levels = levels[::-1]  # an ascent is measured from the bottom up
        prof_rows.append(np.full(len(levels), p))
        level_rows.append(levels)
    prof_rows = np.concatenate(prof_rows)
    level_rows = np.concatenate(level_rows)
    rows = (prof_rows, level_rows)
    profile_number = np.zeros(src.dimensions["N_PROF"].size, dtype=np.int32)
    profile_number[profiles] = np.arange(1, len(profiles) + 1)

    dst.createDimension("N_MEASUREMENTS", len(prof_rows))

    def add(name, values, attrs, dtype=None):
        dtype = dtype or values.dtype
        fill = np.nan if np.dtype(dtype).kind == "f" else None
        var = dst.createVariable(name, dtype, ("N_MEASUREMENTS",), zlib=True, fill_value=fill)
        var.setncatts(attrs)
        var[:] = values

    times = juld[prof_rows] * 86400.0 + _JULD_EPOCH
    add(
        "TIME",
        times,
        {
            "long_name": "Time of the profile (shared by all its levels)",
            "standard_name": "time",
            "units": "seconds since 1970-01-01T00:00:00Z",
        },
    )
    add("LATITUDE", lat[prof_rows], {"long_name": "Latitude of the profile", "units": "degree_north"})
    add("LONGITUDE", lon[prof_rows], {"long_name": "Longitude of the profile", "units": "degree_east"})
    add(
        "CYCLE_NUMBER",
        src["CYCLE_NUMBER"][:][prof_rows],
        {"long_name": "Float cycle number", "units": "1"},
        dtype="i4",
    )
    add("PROFILE_NUMBER", profile_number[prof_rows], {"long_name": "Profile number, in time order", "units": "1"})
    add(
        "PROFILE_DIRECTION",
        np.where(direction[prof_rows] == b"A", -1, 1).astype(np.int8),
        {"long_name": "Profile direction (-1=ascent, 1=descent)", "units": "1"},
    )

    for name, var in src.variables.items():
        if var.dimensions != ("N_PROF", "N_LEVELS") or var.dtype.kind == "S" or name.endswith(_SKIP_SUFFIXES):
            continue
        values = _numeric(var, rows)
        attrs = {k: var.getncattr(k) for k in ("long_name", "standard_name", "units") if k in var.ncattrs()}
        add(name, values.astype(np.float32), attrs)
        if name + "_QC" in src.variables:
            add(
                name + "_QC",
                _flags(src[name + "_QC"], values, rows),
                {"long_name": f"Quality flag for {name} (Argo reference table 2)", "units": "1"},
            )

    wmo = _chars(src["PLATFORM_NUMBER"])[0]
    attrs = {k: src.getncattr(k) for k in _KEEP_ATTRS if k in src.ncattrs()}
    if "id" in src.ncattrs():
        attrs["doi"] = src.getncattr("id")
    attrs.update(
        {
            "title": f"Argo float {wmo}",
            "id": wmo,
            "wmo_id": wmo,
            "platform_type": "Argo float",
            "platform_model": _chars(src["PLATFORM_TYPE"])[0],
            "project_name": _chars(src["PROJECT_NAME"])[0],
            "data_centre": _chars(src["DATA_CENTRE"])[0],
            "data_type": b"".join(src["DATA_TYPE"][:]).decode("ascii", "replace").strip(),
            # The info strip's Deployed / Last data dates.
            "time_coverage_start": _iso(times.min()),
            "time_coverage_end": _iso(times.max()),
        }
    )
    dst.setncatts(attrs)


def _iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
