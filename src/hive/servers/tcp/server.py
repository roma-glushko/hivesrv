import asyncio
import logging
import sys
from functools import partial

from hive.config import Config
from hive.servers.tcp.http.http11 import HTTP11Protocol
from hive.servers.base import Server
from hive.servers.tcp.state import TCPServerState
from hive.telemetry.logs import Logs

logger = logging.getLogger(__name__)


class TCPServer(Server):
    def __init__(self, config: Config) -> None:
        self._config = config

        self._state = TCPServerState()
        self._server = None
        self._should_exit = False

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
        await self.startup()
        await self._main_loop()
        await self.shutdown()

    async def _main_loop(self) -> None:
        """
        TODO: get rid of _main_loop method
        """
        while not self._should_exit:
            await asyncio.sleep(0.1)

    async def shutdown(self) -> None:
        """
        TODO: Implement graceful shutdown
        """
        self._should_exit = True
