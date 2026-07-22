from __future__ import annotations

import typing

import httpx
from fastapi.testclient import TestClient
from starlette.testclient import _AsyncBackend, _is_asgi3, _TestClientTransport, _WrapASGI2
from starlette.types import ASGIApp


class CompatTestClient(TestClient):
    """Starlette TestClient variant that avoids httpx's deprecated app shortcut."""

    def __init__(
        self,
        app: ASGIApp,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        backend: typing.Literal["asyncio", "trio"] = "asyncio",
        backend_options: dict[str, typing.Any] | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> None:
        self.async_backend = _AsyncBackend(
            backend=backend,
            backend_options=backend_options or {},
        )
        if _is_asgi3(app):
            asgi_app = app
        else:
            app = typing.cast(typing.Any, app)
            asgi_app = _WrapASGI2(app)
        self.app = asgi_app
        self.app_state: dict[str, typing.Any] = {}
        transport = _TestClientTransport(
            self.app,
            portal_factory=self._portal_factory,
            raise_server_exceptions=raise_server_exceptions,
            root_path=root_path,
            app_state=self.app_state,
        )
        if headers is None:
            headers = {}
        headers.setdefault("user-agent", "testclient")

        httpx.Client.__init__(
            self,
            base_url=base_url,
            headers=headers,
            transport=transport,
            follow_redirects=follow_redirects,
            cookies=cookies,
        )
