import asyncio
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hive.servers.base import Server

GRACEFUL_SHUTDOWN_SIGNALS = (
    signal.SIGTERM,  # Kubernetes sends it when pod termination started
)

FORCE_SHUTDOWN_SIGNALS = (
    signal.SIGINT,  # Sent by Ctrl+C.
    # Kubernetes also sends signal.SIGKILL after the graceful termination timeout + 2s
)


def setup_signal_handlers(server: "Server") -> None:
    loop = asyncio.get_event_loop()

    try:
        for sig in GRACEFUL_SHUTDOWN_SIGNALS:
            loop.add_signal_handler(sig, server.on_shutdown_signal, True, sig)

        for sig in FORCE_SHUTDOWN_SIGNALS:
            loop.add_signal_handler(sig, server.on_shutdown_signal, False, sig)

    except NotImplementedError:  # pragma: no cover
        # Windows
        # TODO: Not sure I want to handle that
        ...
