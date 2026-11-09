"""OG1 gliders (Slocum, Seaglider) and NOC's Autosub Long Range: the files the app was built
for. Claims any file no other platform does."""

from pathlib import Path
from functools import partial

from ..core import derive_logic
from .base import Platform

# NERC B76 platform-vocabulary codes seen in BODC OG1 files → icon kind.
_B76_KIND = {
    "B7600001": "slocum",  # Teledyne Webb Research Slocum G2 glider
    "B7600029": "slocum",  # Teledyne Webb Research Slocum G3S glider
    "B7600002": "seaglider",  # Kongsberg Seaglider
    "B7600021": "alr",  # NOC Autosub Long Range 1500
}


class OG1(Platform):
    name = "og1"
    presets_file = Path(__file__).with_name("og1_presets.json")
    derive_steps = (
        ("TIME QC", derive_logic.compute_time_qc),
        ("CTD", derive_logic.compute_ctd),
        ("Second CTD", partial(derive_logic.compute_ctd, suffix="2")),
        ("Profile", derive_logic.compute_profiles),
        ("Backscatter", derive_logic.compute_backscatter),
    )

    def detect(self, attrs, filename):
        """'slocum' | 'seaglider' | 'alr' | '' (generic marker), never None."""
        vocab = attrs.get("platform_vocabulary", "")
        for code, kind in _B76_KIND.items():
            if code in vocab:
                return kind
        text = " ".join(
            attrs.get(k, "")
            for k in ("platform_type", "platform_model", "platform", "instrument", "id", "title", "source")
        ).lower()
        text += " " + filename.lower()
        if "slocum" in text:
            return "slocum"
        if "seaglider" in text or "sea glider" in text:
            return "seaglider"
        if "autosub" in text or "alr" in text.replace("_", " ").split() or filename.lower().startswith("alr"):
            return "alr"
        return ""
