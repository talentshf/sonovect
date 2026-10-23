"""Enforce authentication and an aggregate bound before multipart spooling."""
import hmac
from starlette.responses import JSONResponse


class PayloadTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async def reject():
            response = JSONResponse({"type": "urn:sonovect:error:upload_limit_exceeded",
                "title": "upload_limit_exceeded", "status": 413, "code": "upload_limit_exceeded",
                "instance": scope["path"]}, status_code=413, media_type="application/problem+json")
            await response(scope, receive, send)
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    if int(value) > self.maximum:
                        return await reject()
                except ValueError:
                    pass
        total = 0
        exceeded = rejected = False
        async def bounded():
            nonlocal total, exceeded
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.maximum:
                exceeded = True
                raise PayloadTooLarge()
            return message
        async def guarded_send(message):
            nonlocal rejected
            # Frameworks can translate a receive exception to a parse error.
            # Preserve the capacity response even in that case.
            if exceeded:
                if not rejected:
                    rejected = True
                    await reject()
                return
            await send(message)
        try:
            await self.app(scope, bounded, guarded_send)
        except PayloadTooLarge:
            if not rejected:
                await reject()


class BearerGate:
    """Authenticate versioned requests without receiving or parsing their body."""
    def __init__(self, app, token):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/v1" or path.startswith("/v1/")):
            values = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
            scheme, _, credential = values[0].partition(b" ") if len(values) == 1 else (b"", b"", b"")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(credential, self.token):
                response = JSONResponse({"type": "urn:sonovect:error:authentication_required",
                    "title": "authentication_required", "status": 401, "code": "authentication_required",
                    "instance": path}, status_code=401, media_type="application/problem+json",
                    headers={"WWW-Authenticate": "Bearer"})
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
