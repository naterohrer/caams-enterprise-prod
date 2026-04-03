from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _real_ip(request: Request) -> str:
    """Return the real client IP, respecting X-Forwarded-For behind a reverse proxy.

    Takes only the first (leftmost) address from X-Forwarded-For, which is set
    by the client and forwarded by trusted proxies.  Falls back to the direct
    connection address when the header is absent (i.e. no proxy in front).

    NOTE: uvicorn must be started with --proxy-headers --forwarded-allow-ips=<proxy_cidr>
    so that only forwarded IPs from trusted proxies are accepted.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_real_ip)
