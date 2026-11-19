"""Injectable time source: the Groq rate limiter and client read the time and sleep only through a Clock."""

from __future__ import annotations

import time


class Clock:
    """Real wall-clock time; tests pass a subclass or look-alike with a simulated `now` and `sleep`."""

    def now(self) -> float:
        """Seconds since the epoch."""
        return time.time()

    def sleep(self, seconds: float) -> None:
        """Block for `seconds`."""
        time.sleep(seconds)
