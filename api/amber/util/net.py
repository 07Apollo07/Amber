"""Client IP resolution that can't be spoofed through X-Forwarded-For."""

import ipaddress

from fastapi import Request

from amber.util.config import Settings


def _is_trusted(addr: str, settings: Settings) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in settings.trusted_networks)


def client_ip(request: Request, settings: Settings) -> str | None:
    """The address of whoever connected to us, unless that's a trusted proxy.

    Then X-Forwarded-For is walked from the right (the entries our own proxies appended)
    and the first address that isn't a trusted proxy is the client. Entries further left
    are client-supplied and ignored.
    """
    peer = request.client.host if request.client else None
    if peer is None or not _is_trusted(peer, settings):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, settings):
            return hop
    return peer
