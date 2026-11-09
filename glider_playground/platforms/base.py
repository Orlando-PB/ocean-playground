from pathlib import Path

from ..core import presets_logic


class Platform:
    """One kind of platform (vehicle or instrument). Subclasses set the attributes and
    implement ``detect``; see og1.py for the full example."""

    name = ""  # registry key, stored on each file's record as "platform"
    presets_file: Path = None  # this platform's plot presets + dashboard views
    # (label, fn) pairs run once per file after preload, in order; see derive_logic.derive_all_extra_variables.
    derive_steps = ()
    # {key, title, credit, credit_full, url, empty?} for the Files panel's Live section if live_entries gives a feed, else None.
    live_source = None

    def detect(self, attrs: dict, filename: str):
        """The file's icon kind ('' if unknown) if this platform claims it, else None.
        ``attrs`` are the file's global attributes, keys lower-cased."""
        raise NotImplementedError

    def normalise(self, path: str):
        """Rewrite, in place, a file of this platform that we own (a download or an upload) into the names
        the app reads (TIME, LATITUDE, LONGITUDE, ...). Nothing to do for files that already use them."""

    def live_entries(self, days_active: int):
        """This platform's own live feed, as entries for server/erddap_fetch, or None if it has none
        (or its server didn't answer)."""
        return None

    def presets(self) -> dict:
        return presets_logic.load_json(self.presets_file, empty={"axes": {}, "presets": {}, "views": {}})
