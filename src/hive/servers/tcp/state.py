import asyncio
import weakref


class TCPServerState:
    def __init__(self) -> None:
        self.total_requests = 0
        self.last_request_at = 0
        self.connections: set["asyncio.Protocol"] = set()
        self.tasks: weakref.WeakSet[asyncio.Task] = weakref.WeakSet()
