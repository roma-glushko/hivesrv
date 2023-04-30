import asyncio
import logging
import sys
from functools import partial
from typing import Optional

from hive.config import Config
from hive.servers.tcp.http.http11 import HTTP11Protocol
from hive.servers.base import Server
from hive.servers.tcp.state import TCPServerState
from hive.signals import setup_signal_handlers
from hive.telemetry.logs import Logs

logger = logging.getLogger(__name__)


class TCPServer(Server):
    def __init__(self, config: Config) -> None:
        self._config = config

        self._state = TCPServerState()
        self._server = None

        self._is_graceful_shutdown = asyncio.Event()
        self._is_foreceful_shutdown = asyncio.Event()

    async def startup(self) -> None:
        config = self._config
        loop = asyncio.get_running_loop()

        protocol_factory = partial(HTTP11Protocol, config=self._config, server_state=self._state)

        try:
            self._server = await loop.create_server(
                protocol_factory,
                host=config.host,
                port=config.port,
                # ssl=config.ssl, TODO: support SSL later
                backlog=config.backlog,
            )
        except OSError as exc:
            # logger.error(exc)
            sys.exit(1)

        assert self._server.sockets is not None
        logger.info(Logs.HIVE_SERVER_STARTED, extra={"host": config.host, "port": config.port})

    async def serve(self) -> None:
        setup_signal_handlers(self)

        await self.startup()
        await self._main_loop()
        await self.shutdown()

    async def _main_loop(self) -> None:
        """
        TODO: get rid of _main_loop method
        """

        while not self._is_graceful_shutdown.is_set() and not self._is_foreceful_shutdown.is_set():
            await asyncio.sleep(0.1)

    def on_shutdown_signal(self, graceful_shutdown: bool = True, signal: Optional[int] = None) -> None:
        logger.info(Logs.HIVE_SERVER_SIGNAL_RECEIVED, extra={"signal": signal})

        if graceful_shutdown:
            logger.info(Logs.HIVE_SERVER_SHUTDOWN_GRACEFUL)
            self._is_graceful_shutdown.set()
            return

        logger.info(Logs.HIVE_SERVER_SHUTDOWN_FORCEFUL)
        self._is_foreceful_shutdown.set()

    async def shutdown(self, shutdown_threshold_sec: int = 10) -> None:
        """
        TODO: Implement graceful shutdown
        """
        loop = asyncio.get_running_loop()

        while loop.time() - self._state.last_request_at < shutdown_threshold_sec and not self._is_foreceful_shutdown.is_set():
            logger.info(Logs.HIVE_SERVER_SHUTDOWN_WAIT_FOR_NO_REQUESTS)
            await asyncio.sleep(0.5)

        if not self._is_foreceful_shutdown.is_set():
            # wait until all in-flight tasks are done
            await asyncio.gather(*self._state.tasks)

        await self._cleanup()
        logger.info(Logs.HIVE_SERVER_SHUTDOWN_COMPLETED)

    async def _cleanup(self) -> None:
        for task in self._state.tasks:
            task.cancel()

        await asyncio.gather(*self._state.tasks)

        self._server.close()
        await self._server.wait_closed()

        for connection in list(self._state.connections):
            connection.shutdown()

        await asyncio.sleep(0.1)

        if self._state.connections and not self._is_foreceful_shutdown.is_set:
            while self._state.connections and not self._is_foreceful_shutdown.is_set():
                await asyncio.sleep(0.1)
