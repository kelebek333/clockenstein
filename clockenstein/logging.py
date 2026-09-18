import sys


VERBOSE_KEY = "verbose"


class Logger:
    def __init__(self, settings, prefix):
        self.settings = settings
        self.prefix = prefix
        self.verbose = settings.get_boolean(VERBOSE_KEY)
        settings.connect(f"changed::{VERBOSE_KEY}", self._verbose_changed)

    def _verbose_changed(self, settings, _key):
        verbose = settings.get_boolean(VERBOSE_KEY)
        if verbose:
            self.verbose = True
            self.log("Verbose logging enabled")
        else:
            self.log("Verbose logging disabled")
            self.verbose = False

    def log(self, message):
        if self.verbose:
            print(f"{self.prefix}: {message}", flush=True)

    def warning(self, message):
        print(f"{self.prefix}: Warning: {message}", flush=True)

    def error(self, message):
        print(f"{self.prefix}: Error: {message}", file=sys.stderr, flush=True)
