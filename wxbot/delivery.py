"""One permission boundary for all queued outbound messages."""
import queue
import threading


class SendNotStarted(RuntimeError):
    """The send action was never submitted to the chat client."""


class ControlledSendQueue(queue.Queue):
    def __init__(self, is_paused, allow_auto_send, on_blocked, *, is_closed=None):
        super().__init__()
        self._is_paused = is_paused
        self._allow_auto_send = allow_auto_send
        self._on_blocked = on_blocked
        self._is_closed = is_closed
        self._generation = 0
        self._state_lock = threading.RLock()
        self._producer = threading.local()

    def begin_production(self):
        """Bind a scan/poll to the run in which it began, including across awaits."""
        with self._state_lock:
            self._producer.generation = self._generation

    def capture_generation(self):
        """Carry the producer's generation into a separate worker thread."""
        with self._state_lock:
            return getattr(self._producer, "generation", self._generation)

    def permitted(self, manual=False, *, generation=None):
        with self._state_lock:
            if self._is_closed is not None and self._is_closed():
                return False
            if manual:
                return True
            if self._is_paused():
                return False
            if generation is None:
                generation = self.capture_generation()
            if generation != self._generation:
                return False
            return self._allow_auto_send()

    def put(self, item, block=True, timeout=None):
        with self._state_lock:
            if self.permitted(manual=item[0] == "manual"):
                return super().put(item, block=block, timeout=timeout)
        self._on_blocked(item, "自动发送已停止或当前为仅人工模式")

    def cancel_pending(self):
        """Invalidate in-flight producers and retain queued messages for human review."""
        blocked = []
        with self._state_lock:
            self._generation += 1
            while not self.empty():
                blocked.append(self.get_nowait())
                self.task_done()
        for item in blocked:
            self._on_blocked(item, "已停止，消息未发送")
