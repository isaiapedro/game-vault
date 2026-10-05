"""Start the static release on loopback or an explicitly selected private LAN IPv4."""

from __future__ import annotations

from ipaddress import IPv4Address, ip_address
import os

import uvicorn


def validated_bind_host(value: str) -> str:
    try:
        address = ip_address(value)
    except ValueError as error:
        raise ValueError("GAME_VAULT_BIND_HOST must be a literal IPv4 address") from error
    if not isinstance(address, IPv4Address):
        raise ValueError("GAME_VAULT_BIND_HOST must be an IPv4 address")
    if address == IPv4Address("127.0.0.1"):
        return str(address)
    if not (address.is_private and not address.is_loopback and not address.is_link_local
            and not address.is_unspecified and not address.is_multicast and not address.is_reserved):
        raise ValueError("GAME_VAULT_BIND_HOST must be loopback or a private LAN IPv4 address")
    return str(address)


def main() -> None:
    host = validated_bind_host(os.environ.get("GAME_VAULT_BIND_HOST", "127.0.0.1"))
    uvicorn.run("src.api.static_main:app", host=host, port=4200)


if __name__ == "__main__":
    main()
