from __future__ import annotations

import ipaddress


def scope_url_from_address(value: str) -> str:
    """Build the Tektronix web-interface URL from a legacy instrument address."""
    address = value.strip().split(maxsplit=1)[0] if value.strip() else ""
    if not address:
        raise ValueError("enter an oscilloscope IP address")
    if address.count(":") == 1:
        address = address.split(":", 1)[0]
    try:
        host = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as error:
        raise ValueError(f"invalid oscilloscope IPv4 address: {value!r}") from error
    return f"http://{host}/Tektronix/"
