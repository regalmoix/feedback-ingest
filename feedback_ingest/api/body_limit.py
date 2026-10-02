from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1 << 20


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        declared = int(dict(scope.get("headers", ())).get(b"content-length", b"0"))
        seen = 0

        async def capped() -> Message:  # a chunked body has no Content-Length to trust
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if max(seen, declared) > MAX_BODY_BYTES:
                raise HTTPException(413, detail="body too large")
            return message

        await self.app(scope, capped, send)
