"""Saildrone uncrewed surface vehicles, from NOAA PMEL's ERDDAP (CF trajectory files with lowercase
time/latitude/longitude). Live: every PMEL Saildrone dataset with data in the past week, as
5-minute means to keep the downloads small."""

import calendar
import logging
import re
import time
from pathlib import Path

import numpy as np
import requests
from netCDF4 import Dataset

from ..core import derive_logic
from .base import Platform

ERDDAP = "https://data.pmel.noaa.gov/pmel/erddap"
REFRESH_AFTER = 6 * 3600  # re-download once PMEL has this much newer data than our copy
BIN = "5minutes"
_RENAMES = {"time": "TIME", "latitude": "LATITUDE", "longitude": "LONGITUDE"}
# Angles can't be averaged (359° and 1° would give 180°): left out of the binned download.
# Wind direction is rebuilt from the averaged east/north components in normalise.
_ANGLE = re.compile(r"direction|course_over_ground|yaw|wing_angle|wing_heading")
_HTTP_TIMEOUT = 30

log = logging.getLogger(__name__)
_variables_cache = {}  # dataset id -> variables to download


class Saildrone(Platform):
    name = "saildrone"
    presets_file = Path(__file__).with_name("saildrone_presets.json")
    derive_steps = (("TIME QC", derive_logic.compute_time_qc),)
    live_source = {
        "key": "pmel",
        "title": "NOAA PMEL Saildrones",
        "credit": "Data provided by NOAA PMEL",
        "credit_full": "Live data provided by NOAA's Pacific Marine Environmental Laboratory (PMEL), CC0.",
        "url": "https://data.pmel.noaa.gov/pmel/erddap/",
    }

    def detect(self, attrs, filename):
        text = " ".join(attrs.get(k, "") for k in ("title", "platform", "platform_type", "id")).lower()
        if "saildrone" in text or re.match(r"sd\d{4}", filename.lower()):
            return "saildrone"
        return None

    def normalise(self, path):
        """In place, on a file we own: OG1 names for time/lat/lon, and wind direction from the components
        when the file is binned (it isn't averaged directly)."""
        with Dataset(path, "r+") as nc:
            for old, new in _RENAMES.items():
                if old in nc.variables and new not in nc.variables:
                    nc.renameVariable(old, new)
            lon = nc.variables["LONGITUDE"][:].filled(np.nan) if "LONGITUDE" in nc.variables else None
            if lon is not None:
                # A 5-minute bin straddling 180° averages to a longitude somewhere in between: drop it.
                straddled = np.zeros(lon.shape, dtype=bool)
                straddled[1:-1] = (np.abs(lon[1:-1]) < 170) & (np.abs(lon[:-2]) > 170) & (np.abs(lon[2:]) > 170)
                if straddled.any():
                    lon[straddled] = np.nan
                    nc.variables["LONGITUDE"][:] = np.ma.masked_invalid(lon)
            have = nc.variables
            if "wind_direction_world_filtered" not in have and "wind_speed_world_e_filtered" in have:
                east = have["wind_speed_world_e_filtered"][:].filled(np.nan)
                north = have["wind_speed_world_n_filtered"][:].filled(np.nan)
                var = nc.createVariable(
                    "wind_direction_world_filtered",
                    "f4",
                    have["wind_speed_world_e_filtered"].dimensions,
                    fill_value=np.nan,
                )
                var.long_name = "Wind from direction (from the averaged wind components)"
                var.units = "degrees"
                var[:] = np.degrees(np.arctan2(-east, -north)) % 360

    def live_entries(self, days_active):
        """Every PMEL Saildrone dataset with data in the past ``days_active`` days, as live-feed entries
        (see server/erddap_fetch), or None if PMEL didn't answer."""
        try:
            r = requests.get(
                f"{ERDDAP}/tabledap/allDatasets.json?datasetID,maxTime&title=~%22.*%5BSs%5Daildrone.*%22",
                timeout=_HTTP_TIMEOUT,
            )
            r.raise_for_status()
            rows = r.json()["table"]["rows"]
        except Exception as e:
            log.warning("PMEL Saildrone listing failed: %s", e)
            return None
        cutoff = time.time() - days_active * 86400
        entries = []
        for dataset, max_time in rows:
            if not dataset or not max_time:
                continue
            server_mtime = _epoch(max_time)
            if server_mtime < cutoff:
                continue
            variables = _variables(dataset)
            if not variables:
                continue
            query = ",".join(variables) + f"&orderByMean(%22time/{BIN}%22)"
            entries.append(
                {
                    "dataset": dataset,
                    "filename": f"{dataset}.nc",
                    "url": f"{ERDDAP}/tabledap/{dataset}.nc?{query}",
                    "info_url": f"{ERDDAP}/info/{dataset}/index.json",
                    "server_mtime": server_mtime,
                    "refresh_after": REFRESH_AFTER,
                    "platform": self.name,
                    "source": self.live_source["key"],
                }
            )
        return entries


def _epoch(iso: str) -> float:
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def _variables(dataset: str) -> list:
    """The dataset's numeric variables minus the *_rms spreads and angles (see _ANGLE), or [] on failure."""
    if dataset in _variables_cache:
        return _variables_cache[dataset]
    try:
        r = requests.get(f"{ERDDAP}/info/{dataset}/index.json", timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        rows = r.json()["table"]["rows"]
    except Exception as e:
        log.warning("PMEL variable list failed for %s: %s", dataset, e)
        return []
    # rows are [row type, variable, attribute, data type, value]
    names = [row[1] for row in rows if row[0] == "variable" and row[3] != "String"]
    keep = [n for n in names if not (n.endswith("_rms") or _ANGLE.search(n))]
    _variables_cache[dataset] = keep
    return keep
