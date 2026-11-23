from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredDevice:
    host: str
    address: str
    identity: str


def parse_subnet(value: str) -> tuple[str, ...]:
    text = value.strip()
    try:
        network = ipaddress.IPv4Network(text + "/24" if "/" not in text else text, strict=False)
    except ipaddress.AddressValueError as error:
        raise ValueError(f"invalid subnet: {value!r}") from error
    if network.prefixlen != 24:
        raise ValueError("subnet discovery currently requires a /24 network")
    return tuple(str(ipaddress.IPv4Address(address)) for address in network.hosts())


def probe_raw_tcp(host: str, port: int = 5025, timeout: float = 0.15) -> str | None:
    connection: socket.socket | None = None
    try:
        connection = socket.create_connection((host, port), timeout=timeout)
        connection.settimeout(timeout)
        connection.sendall(b"*IDN?\n")
        response = connection.recv(4096)
        identity = response.decode("utf-8", errors="replace").strip()
        return identity or None
    except (OSError, TimeoutError):
        return None
    finally:
        if connection is not None:
            connection.close()


def scan_subnet(
    subnet: str,
    *,
    timeout: float = 0.15,
    max_workers: int = 64,
) -> tuple[DiscoveredDevice, ...]:
    hosts = parse_subnet(subnet)
    discovered: list[DiscoveredDevice] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(probe_raw_tcp, host, 5025, timeout): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                identity = future.result()
            except Exception:
                identity = None
            if identity:
                discovered.append(
                    DiscoveredDevice(
                        host=host,
                        address=f"raw:{host}:5025",
                        identity=identity,
                    )
                )
    return tuple(sorted(discovered, key=lambda device: ipaddress.IPv4Address(device.host)))
