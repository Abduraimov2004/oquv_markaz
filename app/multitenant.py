"""Bir brauzerда bir nechta markazni bir vaqtda ishlatish.

URL'da /c/{N}/ prefiks bo'lsa — o'sha "slot" (markaz) sessiyasi ishlatiladi.
Masalan: /c/1/owner — 1-tab birinchi markaz, /c/2/owner — 2-tab ikkinchi markaz.
Prefikssiz (oddiy /owner) — "0" slot, ya'ni avvalgidek ishlaydi.

Javobdagi ichki havolalar (/owner, /teacher, /login, /logout) avtomatik prefiks
bilan qayta yoziladi, shunda har tab o'z markazida qoladi.
"""
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

_PREFIX_RE = re.compile(r"^/c/(\d+)(/.*)?$")
_LINK_RE = re.compile(r'(["\'])(/(?:owner|teacher|login|logout)\b)')
_LOC_PREFIXES = ("/owner", "/teacher", "/login", "/logout")


class MultiTenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.scope.get("path", "/")
        m = _PREFIX_RE.match(path)
        if m:
            slot = m.group(1)
            rest = m.group(2) or "/"
            prefix = f"/c/{slot}"
            request.scope["path"] = rest
            request.scope["raw_path"] = rest.encode("utf-8")
            request.state.cslot = slot
            request.state.cprefix = prefix
        else:
            request.state.cslot = "0"
            request.state.cprefix = ""
            prefix = ""

        response = await call_next(request)

        if not prefix:
            return response

        # Redirect (Location) — prefiks qo'shamiz
        loc = response.headers.get("location")
        if loc and loc.startswith(_LOC_PREFIXES) and not loc.startswith(prefix):
            response.headers["location"] = prefix + loc

        # HTML ichidagi havolalarni prefikslaymiz
        ctype = response.headers.get("content-type", "")
        if "text/html" in ctype:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            text = body.decode("utf-8", "ignore")
            text = _LINK_RE.sub(lambda mm: mm.group(1) + prefix + mm.group(2), text)
            data = text.encode("utf-8")
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(content=data, status_code=response.status_code,
                            headers=headers, media_type=response.media_type)
        return response
