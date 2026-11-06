import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType


@dataclass
class FakeMcpServer:
    """A local stand-in for Swiggy's MCP endpoint. It speaks just enough JSON-RPC over HTTP.

    By default it answers every tool call with `tool_payload`. Set `fail_status` to answer every
    POST with that HTTP status instead, or `delay_seconds` to answer slowly.
    `requests` records the (JSON-RPC method, Authorization header) of every POST.
    """

    tool_payload: dict[str, object] = field(default_factory=lambda: {"success": True})
    fail_status: int | None = None
    retry_after: str | None = None
    delay_seconds: float = 0.0
    requests: list[tuple[str, str]] = field(default_factory=list)

    def __enter__(self) -> "FakeMcpServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/im"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = request.get("method", "")
                fake.requests.append((method, self.headers.get("Authorization", "")))
                time.sleep(fake.delay_seconds)
                if fake.fail_status is not None:
                    self._reply(fake.fail_status, headers={"Retry-After": fake.retry_after})
                elif method == "initialize":
                    self._reply_result(request, self._server_info(request["params"]))
                elif method == "tools/call":
                    text = json.dumps(fake.tool_payload)
                    self._reply_result(request, {"content": [{"type": "text", "text": text}]})
                else:
                    self._reply(202)

            def do_GET(self) -> None:
                self._reply(405)

            def do_DELETE(self) -> None:
                self._reply(405)

            def log_message(self, format: str, *args: object) -> None:
                return

            def _server_info(self, params: dict[str, object]) -> dict[str, object]:
                return {
                    "protocolVersion": params["protocolVersion"],
                    "capabilities": {},
                    "serverInfo": {"name": "fake-swiggy", "version": "1"},
                }

            def _reply_result(self, request: dict[str, object], result: dict[str, object]) -> None:
                body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result})
                self._reply(200, body.encode(), {"Content-Type": "application/json"})

            def _reply(
                self, status: int, body: bytes = b"", headers: dict[str, str | None] | None = None
            ) -> None:
                self.send_response(status)
                for name, value in (headers or {}).items():
                    if value is not None:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
