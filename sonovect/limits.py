"""Enforce authentication and an aggregate bound before multipart spooling."""
import hmac
import uuid
from starlette.responses import JSONResponse


def boundary_error(path, status, code):
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    if path == "/api/v1" or path.startswith("/api/v1/"):
        return JSONResponse({"request_id": uuid.uuid4().hex, "code": code, "message": code},
                            status_code=status, headers=headers)
    return JSONResponse({"type": "urn:sonovect:error:" + code, "title": code,
                         "status": status, "code": code, "instance": path},
                        status_code=status, media_type="application/problem+json", headers=headers)


class PayloadTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async def reject():
            response = boundary_error(scope["path"], 413, "upload_limit_exceeded")
            await response(scope, receive, send)
        maximum = min(self.maximum, 65536) if scope.get("path", "").startswith("/api/v1/") else self.maximum
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    if int(value) > maximum:
                        return await reject()
                except ValueError:
                    pass
        total = 0
        exceeded = rejected = False
        async def bounded():
            nonlocal total, exceeded
            message = await receive()
            total += len(message.get("body", b""))
            if total > maximum:
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
        if scope["type"] == "http" and (path == "/v1" or path.startswith("/v1/") or path == "/api/v1" or path.startswith("/api/v1/")):
            values = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
            scheme, _, credential = values[0].partition(b" ") if len(values) == 1 else (b"", b"", b"")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(credential, self.token):
                response = boundary_error(path, 401, "authentication_required")
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
