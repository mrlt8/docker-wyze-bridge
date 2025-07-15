from threading import Lock

from wyzebridge.stream_status import StreamStatus

class StreamState:
    """Thread-safe state management for stream status."""
    def __init__(self, initial_state: StreamStatus = StreamStatus.STOPPED) -> None:
        self._state_value = initial_state
        self._state_lock = Lock()

    def get(self) -> StreamStatus:
        """Get the current stream status."""
        with self._state_lock:
            return self._state_value

    def set(self, value: StreamStatus) -> None:
        """Set the stream status."""
        with self._state_lock:
            self._state_value = value