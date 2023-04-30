import asyncio
import http
import logging
from typing import Optional, Literal, Union, TYPE_CHECKING, Callable, cast
from urllib.parse import unquote, quote

import h11

from hive.config import Config
from hive.servers.tcp.state import TCPServerState

if TYPE_CHECKING:
    from asgiref.typing import (
        ASGIReceiveCallable,
        ASGISendCallable,
        HTTPResponseBodyEvent,
        HTTPResponseStartEvent,
        ASGI3Application,
        ASGIReceiveEvent,
        ASGISendEvent,
        HTTPDisconnectEvent,
        HTTPRequestEvent,
        HTTPResponseBodyEvent,
        HTTPResponseStartEvent,
        HTTPScope,
        WWWScope,
    )

H11Event = Union[
    h11.Request,
    h11.InformationalResponse,
    h11.Response,
    h11.Data,
    h11.EndOfMessage,
    h11.ConnectionClosed,
]

CLOSE_HEADER = (b"connection", b"close")

HIGH_WATER_LIMIT = 65536

logger = logging.getLogger(__name__)


def get_remote_addr(transport: asyncio.Transport) -> Optional[tuple[str, int]]:
    socket_info = transport.get_extra_info("socket")
    if socket_info is not None:
        try:
            info = socket_info.getpeername()
            return (str(info[0]), int(info[1])) if isinstance(info, tuple) else None
        except OSError:  # pragma: no cover
            # This case appears to inconsistently occur with uvloop
            # bound to a unix domain socket.
            return None

    info = transport.get_extra_info("peername")
    if info is not None and isinstance(info, (list, tuple)) and len(info) == 2:
        return (str(info[0]), int(info[1]))
    return None


def get_local_addr(transport: asyncio.Transport) -> Optional[tuple[str, int]]:
    socket_info = transport.get_extra_info("socket")
    if socket_info is not None:
        info = socket_info.getsockname()

        return (str(info[0]), int(info[1])) if isinstance(info, tuple) else None
    info = transport.get_extra_info("sockname")
    if info is not None and isinstance(info, (list, tuple)) and len(info) == 2:
        return (str(info[0]), int(info[1]))
    return None


def is_ssl(transport: asyncio.Transport) -> bool:
    return bool(transport.get_extra_info("sslcontext"))


def get_client_addr(scope: "WWWScope") -> str:
    client = scope.get("client")
    if not client:
        return ""
    return "%s:%d" % client


def get_path_with_query_string(scope: "WWWScope") -> str:
    path_with_query_string = quote(scope["path"])
    if scope["query_string"]:
        path_with_query_string = "{}?{}".format(
            path_with_query_string, scope["query_string"].decode("ascii")
        )
    return path_with_query_string


def _get_status_phrase(status_code: int) -> bytes:
    try:
        return http.HTTPStatus(status_code).phrase.encode()
    except ValueError:
        return b""


STATUS_PHRASES = {
    status_code: _get_status_phrase(status_code) for status_code in range(100, 600)
}


class FlowControl:
    __slots__ = ("_transport", "read_paused", "write_paused", "_is_writable_event")

    def __init__(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        self.read_paused = False
        self.write_paused = False

        self._is_writable_event = asyncio.Event()
        self._is_writable_event.set()

    async def drain(self) -> None:
        await self._is_writable_event.wait()

    def pause_reading(self) -> None:
        if not self.read_paused:
            self.read_paused = True
            self._transport.pause_reading()

    def resume_reading(self) -> None:
        if self.read_paused:
            self.read_paused = False
            self._transport.resume_reading()

    def pause_writing(self) -> None:
        if not self.write_paused:
            self.write_paused = True
            self._is_writable_event.clear()

    def resume_writing(self) -> None:
        if self.write_paused:
            self.write_paused = False
            self._is_writable_event.set()


class RequestResponseCycle:
    def __init__(
        self,
        scope: "HTTPScope",
        conn: h11.Connection,
        transport: asyncio.Transport,
        flow: FlowControl,
        message_event: asyncio.Event,
        on_response: Callable[..., None],
    ) -> None:
        self.scope = scope
        self.conn = conn
        self.transport = transport
        self.flow = flow
        self.message_event = message_event
        self.on_response = on_response

        # Connection state
        self.disconnected = False
        self.keep_alive = True
        self.waiting_for_100_continue = conn.they_are_waiting_for_100_continue

        # Request state
        self.body = b""
        self.more_body = True

        # Response state
        self.response_started = False
        self.response_complete = False

    # ASGI exception wrapper
    async def run_asgi(self, app: "ASGI3Application") -> None:
        try:
            result = await app(  # type: ignore[func-returns-value]
                self.scope, self.receive, self.send
            )
        except BaseException as exc:
            msg = "Exception in ASGI application\n"
            logger.error(msg, exc_info=exc)
            if not self.response_started:
                await self.send_500_response()
            else:
                self.transport.close()
        else:
            if result is not None:
                msg = "ASGI callable should return None, but returned '%s'."
                logger.error(msg, result)
                self.transport.close()
            elif not self.response_started and not self.disconnected:
                msg = "ASGI callable returned without starting response."
                logger.error(msg)
                await self.send_500_response()
            elif not self.response_complete and not self.disconnected:
                msg = "ASGI callable returned without completing response."
                logger.error(msg)
                self.transport.close()
        finally:
            self.on_response = lambda: None

    async def send_500_response(self) -> None:
        response_headers_event: "HTTPResponseStartEvent" = {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"connection", b"close"),
            ],
        }
        response_body_event: "HTTPResponseBodyEvent" = {
            "type": "http.response.body",
            "body": b"Internal Server Error",
            "more_body": False,
        }

        await self.send(response_headers_event)
        await self.send(response_body_event)

    # ASGI interface
    async def send(self, message: "ASGISendEvent") -> None:
        message_type = message["type"]

        if self.flow.write_paused and not self.disconnected:
            await self.flow.drain()

        if self.disconnected:
            return

        if not self.response_started:
            # Sending response status line and headers
            if message_type != "http.response.start":
                msg = "Expected ASGI message 'http.response.start', but got '%s'."
                raise RuntimeError(msg % message_type)
            message = cast("HTTPResponseStartEvent", message)

            self.response_started = True
            self.waiting_for_100_continue = False

            status_code = message["status"]
            message_headers = cast(
                list[tuple[bytes, bytes]], message.get("headers", [])
            )

            headers = message_headers  # self.default_headers +

            if CLOSE_HEADER in self.scope["headers"] and CLOSE_HEADER not in headers:
                headers = headers + [CLOSE_HEADER]

            logger.info(
                '%s - "%s %s HTTP/%s" %d',
                get_client_addr(self.scope),
                self.scope["method"],
                get_path_with_query_string(self.scope),
                self.scope["http_version"],
                status_code,
            )

            # Write response status line and headers
            reason = STATUS_PHRASES[status_code]
            event = h11.Response(
                status_code=status_code, headers=headers, reason=reason
            )
            output = self.conn.send(event)
            self.transport.write(output)

        elif not self.response_complete:
            # Sending response body
            if message_type != "http.response.body":
                msg = "Expected ASGI message 'http.response.body', but got '%s'."
                raise RuntimeError(msg % message_type)
            message = cast("HTTPResponseBodyEvent", message)

            body = message.get("body", b"")
            more_body = message.get("more_body", False)

            # Write response body
            if self.scope["method"] == "HEAD":
                event = h11.Data(data=b"")
            else:
                event = h11.Data(data=body)
            output = self.conn.send(event)
            self.transport.write(output)

            # Handle response completion
            if not more_body:
                self.response_complete = True
                self.message_event.set()
                event = h11.EndOfMessage()
                output = self.conn.send(event)
                self.transport.write(output)

        else:
            # Response already sent
            msg = "Unexpected ASGI message '%s' sent, after response already completed."
            raise RuntimeError(msg % message_type)

        if self.response_complete:
            if self.conn.our_state is h11.MUST_CLOSE or not self.keep_alive:
                event = h11.ConnectionClosed()
                self.conn.send(event)
                self.transport.close()
            self.on_response()

    async def receive(self) -> "ASGIReceiveEvent":
        if self.waiting_for_100_continue and not self.transport.is_closing():
            event = h11.InformationalResponse(
                status_code=100, headers=[], reason="Continue"
            )
            output = self.conn.send(event)
            self.transport.write(output)
            self.waiting_for_100_continue = False

        if not self.disconnected and not self.response_complete:
            self.flow.resume_reading()
            await self.message_event.wait()
            self.message_event.clear()

        message: "Union[HTTPDisconnectEvent, HTTPRequestEvent]"
        if self.disconnected or self.response_complete:
            message = {"type": "http.disconnect"}
        else:
            message = {
                "type": "http.request",
                "body": self.body,
                "more_body": self.more_body,
            }
            self.body = b""

        return message


class HTTP11Protocol(asyncio.Protocol):
    def __init__(
        self,
        config: Config,
        server_state: TCPServerState,
        _loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self.loop = _loop or asyncio.get_event_loop()
        self.config = config
        self.app = config.app

        self.conn = h11.Connection(h11.SERVER, config.h11_max_incomplete_event_size)

        # self.ws_protocol_class = config.ws_protocol_class
        self.root_path = config.root_path
        # self.limit_concurrency = config.limit_concurrency

        # Timeouts
        self.timeout_keep_alive_task: Optional[asyncio.TimerHandle] = None
        self.timeout_keep_alive = config.timeout_keep_alive_sec

        # Shared server state
        self.server_state = server_state
        self.connections = server_state.connections
        self.tasks = server_state.tasks

        # Per-connection state
        self.transport: asyncio.Transport = None  # type: ignore[assignment]
        self.flow: FlowControl = None  # type: ignore[assignment]
        self.server: Optional[tuple[str, int]] = None
        self.client: Optional[tuple[str, int]] = None
        self.scheme: Optional[Literal["http", "https"]] = None

        # Per-request state
        self.scope: HTTPScope = None  # type: ignore[assignment]
        self.headers: List[Tuple[bytes, bytes]] = None  # type: ignore[assignment]
        self.cycle: RequestResponseCycle = None  # type: ignore[assignment]

    # Protocol interface
    def connection_made(  # type: ignore[override]
        self, transport: asyncio.Transport
    ) -> None:
        self.connections.add(self)

        self.transport = transport
        self.flow = FlowControl(transport)
        self.server = get_local_addr(transport)
        self.client = get_remote_addr(transport)
        self.scheme = "https" if is_ssl(transport) else "http"

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.connections.discard(self)

        if self.cycle and not self.cycle.response_complete:
            self.cycle.disconnected = True

        if self.conn.our_state != h11.ERROR:
            event = h11.ConnectionClosed()
            try:
                self.conn.send(event)
            except h11.LocalProtocolError:
                # Premature client disconnect
                pass

        if self.cycle is not None:
            self.cycle.message_event.set()

        if self.flow is not None:
            self.flow.resume_writing()

        if exc is None:
            self.transport.close()

    def eof_received(self) -> None:
        pass

    def _unset_keepalive_if_required(self) -> None:
        if self.timeout_keep_alive_task is not None:
            self.timeout_keep_alive_task.cancel()
            self.timeout_keep_alive_task = None

    def data_received(self, data: bytes) -> None:
        self._unset_keepalive_if_required()

        self.conn.receive_data(data)
        self.handle_events()

    def handle_events(self) -> None:
        while True:
            try:
                event = self.conn.next_event()
            except h11.RemoteProtocolError:
                msg = "Invalid HTTP request received."
                self.send_400_response(msg)
                return

            event_type = type(event)

            if event_type is h11.NEED_DATA:
                break

            elif event_type is h11.PAUSED:
                # This case can occur in HTTP pipelining, so we need to
                # stop reading any more data, and ensure that at the end
                # of the active request/response cycle we handle any
                # events that have been buffered up.
                self.flow.pause_reading()
                break

            elif event_type is h11.Request:
                self.headers = [(key.lower(), value) for key, value in event.headers]
                raw_path, _, query_string = event.target.partition(b"?")

                self.scope = {  # type: ignore[typeddict-item]
                    "type": "http",
                    "asgi": {
                        "version": self.config.asgi_version,
                        "spec_version": "2.3",
                    },
                    "http_version": event.http_version.decode("ascii"),
                    "server": self.server,
                    "client": self.client,
                    "scheme": self.scheme,
                    "method": event.method.decode("ascii"),
                    "root_path": self.root_path,
                    "path": unquote(raw_path.decode("ascii")),
                    "raw_path": raw_path,
                    "query_string": query_string,
                    "headers": self.headers,
                }

                for name, value in self.headers:
                    if name == b"connection":
                        tokens = [token.lower().strip() for token in value.split(b",")]
                        if b"upgrade" in tokens:
                            self.handle_upgrade(event)
                            return

                # Handle 503 responses when 'limit_concurrency' is exceeded.
                # if self.limit_concurrency is not None and (
                #         len(self.connections) >= self.limit_concurrency
                #         or len(self.tasks) >= self.limit_concurrency
                # ):
                #     app = service_unavailable
                #     message = "Exceeded concurrency limit."
                #     self.logger.warning(message)
                # else:
                #     app = self.app

                app = self.app

                self.cycle = RequestResponseCycle(
                    scope=self.scope,
                    conn=self.conn,
                    transport=self.transport,
                    flow=self.flow,
                    message_event=asyncio.Event(),
                    on_response=self.on_response_complete,
                )

                self.server_state.last_request_at = self.loop.time()
                self.tasks.add(self.loop.create_task(self.cycle.run_asgi(app)))

            elif event_type is h11.Data:
                if self.conn.our_state is h11.DONE:
                    continue

                self.cycle.body += event.data

                if len(self.cycle.body) > HIGH_WATER_LIMIT:
                    self.flow.pause_reading()

                self.cycle.message_event.set()

            elif event_type is h11.EndOfMessage:
                if self.conn.our_state is h11.DONE:
                    self.transport.resume_reading()
                    self.conn.start_next_cycle()
                    continue
                self.cycle.more_body = False
                self.cycle.message_event.set()

    def handle_upgrade(self, event: H11Event) -> None:
        upgrade_value = None
        for name, value in self.headers:
            if name == b"upgrade":
                upgrade_value = value.lower()

        if upgrade_value != b"websocket" or self.ws_protocol_class is None:
            msg = "Unsupported upgrade request."
            # self.logger.warning(msg)
            # from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
            #
            # if AutoWebSocketsProtocol is None:  # pragma: no cover
            #     msg = "No supported WebSocket library detected. Please use 'pip install uvicorn[standard]', or install 'websockets' or 'wsproto' manually."  # noqa: E501
            #     self.logger.warning(msg)
            self.send_400_response(msg)
            return

        self.connections.discard(self)

        output = [event.method, b" ", event.target, b" HTTP/1.1\r\n"]
        for name, value in self.headers:
            output += [name, b": ", value, b"\r\n"]
        output.append(b"\r\n")
        protocol = self.ws_protocol_class(  # type: ignore[call-arg]
            config=self.config, server_state=self.server_state
        )
        protocol.connection_made(self.transport)
        protocol.data_received(b"".join(output))
        self.transport.set_protocol(protocol)

    def send_400_response(self, msg: str) -> None:

        reason = STATUS_PHRASES[400]
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"connection", b"close"),
        ]
        event = h11.Response(status_code=400, headers=headers, reason=reason)
        output = self.conn.send(event)
        self.transport.write(output)
        event = h11.Data(data=msg.encode("ascii"))
        output = self.conn.send(event)
        self.transport.write(output)
        event = h11.EndOfMessage()
        output = self.conn.send(event)
        self.transport.write(output)
        self.transport.close()

    def on_response_complete(self) -> None:
        self.server_state.total_requests += 1

        if self.transport.is_closing():
            return

        # Set a short Keep-Alive timeout.
        self._unset_keepalive_if_required()

        self.timeout_keep_alive_task = self.loop.call_later(
            self.timeout_keep_alive, self.timeout_keep_alive_handler
        )

        # Unpause data reads if needed.
        self.flow.resume_reading()

        # Unblock any pipelined events.
        if self.conn.our_state is h11.DONE and self.conn.their_state is h11.DONE:
            self.conn.start_next_cycle()
            self.handle_events()

    def shutdown(self) -> None:
        """
        Called by the server to commence a graceful shutdown.
        """
        if self.cycle is None or self.cycle.response_complete:
            self.conn.send(h11.ConnectionClosed())
            self.transport.close()
        else:
            self.cycle.keep_alive = False

    def pause_writing(self) -> None:
        """
        Called by the transport when the write buffer exceeds the high water mark.
        """
        self.flow.pause_writing()

    def resume_writing(self) -> None:
        """
        Called by the transport when the write buffer drops below the low water mark.
        """
        self.flow.resume_writing()

    def timeout_keep_alive_handler(self) -> None:
        """
        Called on a keep-alive connection if no new data is received after a short
        delay.
        """
        if not self.transport.is_closing():
            self.conn.send(h11.ConnectionClosed())
            self.transport.close()


async def service_unavailable(
        scope: "Scope", receive: "ASGIReceiveCallable", send: "ASGISendCallable"
) -> None:
    response_start: "HTTPResponseStartEvent" = {
        "type": "http.response.start",
        "status": 503,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"connection", b"close"),
        ],
    }
    response_body: "HTTPResponseBodyEvent" = {
        "type": "http.response.body",
        "body": b"Service Unavailable",
        "more_body": False,
    }

    await send(response_start)
    await send(response_body)
