"""Standard-library HTTP probing via a SOCKS5 endpoint."""

from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import SplitResult
from urllib.parse import urlsplit


ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@dataclass(slots=True)
class HttpProbeTarget:
    """Define one HTTP probe target."""

    url: str
    user_agent: str = "ScholarOutboundManager/0.1"
    max_body_bytes: int = 16384


@dataclass(slots=True)
class HttpProbeResponse:
    """Represent one low-level HTTP probe result."""

    url: str
    status_code: int | None
    reason: str | None
    headers: dict[str, str]
    body_prefix: str
    elapsed_ms: int | None
    timed_out: bool
    error: str | None


@dataclass(slots=True)
class SocksEndpoint:
    """Define one SOCKS5 endpoint."""

    host: str
    port: int


@dataclass(slots=True)
class ParsedProbeUrl:
    """Represent one parsed probe URL."""

    scheme: str
    host: str
    port: int
    request_target: str


def probe_http_via_socks(
    target: HttpProbeTarget,
    socks: SocksEndpoint,
    timeout_seconds: float,
) -> HttpProbeResponse:
    """Probe one HTTP or HTTPS URL through a SOCKS5 no-auth endpoint."""
    started_at = time.monotonic()
    try:
        _validate_target(target)
        _validate_socks_endpoint(socks)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0.")
        parsed = _parse_url(target.url)

        with _open_socks_connection(socks, timeout_seconds) as raw_socket:
            _socks5_connect(
                sock=raw_socket,
                host=parsed.host,
                port=parsed.port,
                timeout_seconds=timeout_seconds,
            )
            transport_socket = raw_socket
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                transport_socket = context.wrap_socket(raw_socket, server_hostname=parsed.host)
                transport_socket.settimeout(timeout_seconds)

            _send_http_get(
                sock=transport_socket,
                parsed=parsed,
                user_agent=target.user_agent,
            )
            status_code, reason, headers, body_prefix = _read_http_response(
                sock=transport_socket,
                url=target.url,
                max_body_bytes=target.max_body_bytes,
            )
    except ValueError as exc:
        return _error_response(target.url, started_at, str(exc), timed_out=False)
    except socket.timeout:
        return _error_response(target.url, started_at, "Probe timed out.", timed_out=True)
    except TimeoutError:
        return _error_response(target.url, started_at, "Probe timed out.", timed_out=True)
    except ssl.SSLError as exc:
        return _error_response(target.url, started_at, f"SSL error: {exc}", timed_out=False)
    except (ConnectionRefusedError, OSError, http.client.HTTPException) as exc:
        return _error_response(target.url, started_at, str(exc), timed_out=False)

    return HttpProbeResponse(
        url=target.url,
        status_code=status_code,
        reason=reason,
        headers=headers,
        body_prefix=body_prefix,
        elapsed_ms=_elapsed_ms(started_at),
        timed_out=False,
        error=None,
    )


def _validate_target(target: HttpProbeTarget) -> None:
    """Validate one probe target."""
    if target.max_body_bytes < 0:
        raise ValueError("max_body_bytes must be greater than or equal to 0.")


def _validate_socks_endpoint(socks: SocksEndpoint) -> None:
    """Validate one SOCKS5 endpoint."""
    if not socks.host:
        raise ValueError("socks.host must not be empty.")
    if socks.port <= 0:
        raise ValueError("socks.port must be greater than 0.")


def _parse_url(url: str) -> ParsedProbeUrl:
    """Parse one probe URL and validate its supported scheme."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme or '<empty>'}.")
    if not parsed.hostname:
        raise ValueError("Probe URL must include a host.")
    port = parsed.port or (80 if parsed.scheme == "http" else 443)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return ParsedProbeUrl(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=port,
        request_target=path,
    )


def _open_socks_connection(socks: SocksEndpoint, timeout_seconds: float) -> socket.socket:
    """Open one TCP connection to the SOCKS endpoint."""
    sock = socket.create_connection((socks.host, socks.port), timeout=timeout_seconds)
    sock.settimeout(timeout_seconds)
    return sock


def _socks5_connect(
    sock: socket.socket,
    host: str,
    port: int,
    timeout_seconds: float,
) -> None:
    """Perform a SOCKS5 no-auth CONNECT handshake for a domain target."""
    del timeout_seconds
    host_bytes = host.encode("idna")
    if len(host_bytes) > 255:
        raise ValueError("SOCKS5 domain name exceeds 255 bytes.")

    sock.sendall(b"\x05\x01\x00")
    greeting_reply = _recv_exact(sock, 2)
    if len(greeting_reply) < 2:
        raise ValueError("SOCKS5 greeting reply is too short.")
    if greeting_reply[0] != 0x05:
        raise ValueError("SOCKS5 greeting reply version is not 5.")
    if greeting_reply[1] != 0x00:
        raise ValueError("SOCKS5 server does not accept no-auth.")

    request = (
        b"\x05\x01\x00\x03"
        + bytes([len(host_bytes)])
        + host_bytes
        + port.to_bytes(2, "big")
    )
    sock.sendall(request)
    reply_head = _recv_exact(sock, 4)
    if len(reply_head) < 4:
        raise ValueError("SOCKS5 connect reply is too short.")
    if reply_head[0] != 0x05:
        raise ValueError("SOCKS5 connect reply version is not 5.")
    if reply_head[1] != 0x00:
        raise ValueError(f"SOCKS5 connect failed with reply code {reply_head[1]}.")

    atyp = reply_head[3]
    if atyp == 0x01:
        _recv_exact(sock, 4 + 2)
        return
    if atyp == 0x03:
        name_length = _recv_exact(sock, 1)[0]
        _recv_exact(sock, name_length + 2)
        return
    if atyp == 0x04:
        _recv_exact(sock, 16 + 2)
        return
    raise ValueError(f"SOCKS5 connect reply used unsupported address type {atyp}.")


def _send_http_get(sock: socket.socket, parsed: ParsedProbeUrl, user_agent: str) -> None:
    """Send one HTTP GET request over the connected transport socket."""
    request = "\r\n".join(
        [
            f"GET {parsed.request_target} HTTP/1.1",
            f"Host: {parsed.host}",
            f"User-Agent: {user_agent}",
            f"Accept: {ACCEPT_HEADER}",
            "Connection: close",
            "",
            "",
        ]
    ).encode("utf-8")
    sock.sendall(request)


def _read_http_response(
    sock: socket.socket,
    url: str,
    max_body_bytes: int,
) -> tuple[int | None, str | None, dict[str, str], str]:
    """Read and parse one HTTP response from the transport socket."""
    del url
    response = http.client.HTTPResponse(sock)
    response.begin()
    body_bytes = response.read(max_body_bytes)
    headers = {key: value for key, value in response.headers.items()}
    body_prefix = _decode_body_prefix(response.headers, body_bytes)
    return response.status, response.reason, headers, body_prefix


def _decode_body_prefix(headers: http.client.HTTPMessage, body_bytes: bytes) -> str:
    """Decode a response body prefix using the declared charset when available."""
    charset = headers.get_content_charset() or "utf-8"
    return body_bytes.decode(charset, errors="replace")


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    """Receive exactly the requested number of bytes or fail."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ValueError("SOCKS5 peer closed the connection unexpectedly.")
        chunks.extend(chunk)
    return bytes(chunks)


def _elapsed_ms(started_at: float) -> int:
    """Return elapsed time in milliseconds from the start timestamp."""
    return int((time.monotonic() - started_at) * 1000)


def _error_response(url: str, started_at: float, error: str, timed_out: bool) -> HttpProbeResponse:
    """Build one transport-level error response."""
    return HttpProbeResponse(
        url=url,
        status_code=None,
        reason=None,
        headers={},
        body_prefix="",
        elapsed_ms=_elapsed_ms(started_at),
        timed_out=timed_out,
        error=error,
    )
