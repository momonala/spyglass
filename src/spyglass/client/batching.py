"""In-memory buffer that ships client data to the server in periodic batches."""

import atexit
import contextlib
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from collections.abc import Hashable

DEFAULT_FLUSH_INTERVAL = 30.0
DEFAULT_MAX_PENDING = 10_000


class Batcher:
    """Buffers items and hands them to ``send`` from a background thread.

    Items added with a ``sum_key`` are merged with any pending item under the same
    key: their ``value`` fields are added together and the latest item's other
    fields (e.g. timestamp) are kept. Everything else is sent as-is, in order.

    ``send`` is called with a non-empty list and must not raise; failed batches
    are dropped. When more than ``max_pending`` plain items pile up (e.g. the
    server is down), the oldest are dropped first.

    Args:
        send: Callable that delivers one batch.
        flush_interval: Seconds between background flushes.
        max_pending: Cap on buffered plain items.
    """

    def __init__(
        self,
        send: Callable[[list[dict]], None],
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_pending: int = DEFAULT_MAX_PENDING,
    ) -> None:
        self._send = send
        self._flush_interval = flush_interval
        self._max_pending = max_pending
        self._reset()
        os.register_at_fork(after_in_child=self._reset)
        atexit.register(self.flush)

    def add(self, item: dict, *, sum_key: Hashable | None = None) -> None:
        with self._lock:
            if sum_key is None:
                self._items.append(item)
            elif sum_key in self._sums:
                merged = {**item, "value": self._sums[sum_key]["value"] + item["value"]}
                self._sums[sum_key] = merged
            else:
                self._sums[sum_key] = item
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True, name="spyglass-flush")
                self._thread.start()

    def flush(self) -> None:
        """Send everything buffered so far, on the calling thread."""
        with self._lock:
            batch = list(self._sums.values()) + list(self._items)
            self._sums = {}
            self._items.clear()
        if batch:
            self._send(batch)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._sums) + len(self._items)

    def _reset(self) -> None:
        # Also runs in a forked child: the parent's lock may be held and its
        # thread doesn't exist here, and its buffer belongs to the parent.
        self._lock = threading.Lock()
        self._items: deque[dict] = deque(maxlen=self._max_pending)
        self._sums: dict[Hashable, dict] = {}
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while True:
            time.sleep(self._flush_interval)
            with contextlib.suppress(Exception):
                self.flush()
