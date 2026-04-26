from __future__ import annotations

import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

from ahadiff.core.errors import InputError

if TYPE_CHECKING:
    from collections.abc import Mapping

_CONNECT_TIMEOUT_SECONDS = 30.0
_TOTAL_TIMEOUT_SECONDS = 60.0
_MAX_REDIRECTS = 3
_MAX_HEADER_BYTES = 65_536
_READ_CHUNK_SIZE = 65_536
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
    )
)
_PRIVATE_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "::1/128",
        "fd00::/8",
    )
)


@dataclass(frozen=True)
class DownloadedPatch:
    body: bytes
    final_url: str
    redirect_count: int
    content_type: str


@dataclass(frozen=True)
class _ResolvedAddress:
    family: socket.AddressFamily
    socktype: socket.SocketKind
    proto: int
    sockaddr: Any
    ip_text: str


@dataclass(frozen=True)
class _HttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes
    content_type: str


def download_patch_url(url: str, *, max_patch_bytes: int) -> DownloadedPatch:
    current_url = url
    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    redirects = 0
    while True:
        if time.monotonic() >= deadline:
            raise InputError("patch URL download timed out after 60 seconds")
        response = _request_once(current_url, max_patch_bytes=max_patch_bytes, deadline=deadline)
        if response.status_code in _REDIRECT_STATUS_CODES:
            if redirects >= _MAX_REDIRECTS:
                raise InputError("patch URL redirect limit exceeded")
            location = response.headers.get("location")
            if not location:
                raise InputError("patch URL redirect missing Location header")
            next_url = urljoin(current_url, location)
            if urlsplit(current_url).scheme == "https" and urlsplit(next_url).scheme == "http":
                raise InputError("patch URL HTTPS redirect must not downgrade to HTTP")
            current_url = next_url
            redirects += 1
            continue
        if not 200 <= response.status_code < 300:
            raise InputError(f"patch URL returned HTTP {response.status_code}")
        return DownloadedPatch(
            body=response.body,
            final_url=current_url,
            redirect_count=redirects,
            content_type=response.content_type,
        )


def _request_once(url: str, *, max_patch_bytes: int, deadline: float) -> _HttpResponse:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise InputError("patch URL scheme must be http or https")
    if not parsed.hostname:
        raise InputError("patch URL must include a hostname")

    port = _port_for_url(parsed)
    addresses = _resolve_public_addresses(parsed.hostname, port)
    if not addresses:
        raise InputError("patch URL DNS lookup returned no usable addresses")

    last_error: OSError | ssl.SSLError | None = None
    for address in addresses:
        raw_socket: socket.socket | None = None
        try:
            raw_socket = _connect_socket(address, deadline=deadline)
            active_socket: socket.socket | ssl.SSLSocket = raw_socket
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                active_socket = context.wrap_socket(raw_socket, server_hostname=parsed.hostname)
                raw_socket = None
            try:
                return _send_http_request(
                    active_socket,
                    parsed_url=url,
                    host=parsed.hostname,
                    port=port,
                    max_patch_bytes=max_patch_bytes,
                    deadline=deadline,
                )
            finally:
                active_socket.close()
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
            if raw_socket is not None:
                raw_socket.close()
            continue
    raise InputError("patch URL download failed") from last_error


def _resolve_public_addresses(hostname: str, port: int) -> list[_ResolvedAddress]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise InputError("patch URL DNS lookup failed") from exc

    addresses: list[_ResolvedAddress] = []
    for family, socktype, proto, _canonname, sockaddr in infos:
        ip_text = str(sockaddr[0])
        _raise_if_private_ip(ip_text)
        addresses.append(
            _ResolvedAddress(
                family=socket.AddressFamily(family),
                socktype=socket.SocketKind(socktype),
                proto=proto,
                sockaddr=sockaddr,
                ip_text=ip_text,
            )
        )
    return addresses


def _raise_if_private_ip(ip_text: str) -> None:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError as exc:
        raise InputError("patch URL DNS returned an invalid IP address") from exc
    mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
    if mapped is not None:
        ip = mapped
    if isinstance(ip, ipaddress.IPv4Address):
        if any(ip in network for network in _PRIVATE_IPV4_NETWORKS):
            raise InputError("patch URL resolved to a blocked private IP address")
    elif any(ip in network for network in _PRIVATE_IPV6_NETWORKS):
        raise InputError("patch URL resolved to a blocked private IP address")
    if not ip.is_global:
        raise InputError("patch URL resolved to a blocked non-public IP address")


def _connect_socket(address: _ResolvedAddress, *, deadline: float) -> socket.socket:
    remaining = _remaining_timeout(deadline, cap=_CONNECT_TIMEOUT_SECONDS)
    sock = socket.socket(address.family, address.socktype, address.proto)
    try:
        sock.settimeout(remaining)
        sock.connect(address.sockaddr)
        sock.settimeout(_remaining_timeout(deadline))
    except OSError:
        sock.close()
        raise
    return sock


def _send_http_request(
    sock: socket.socket | ssl.SSLSocket,
    *,
    parsed_url: str,
    host: str,
    port: int,
    max_patch_bytes: int,
    deadline: float,
) -> _HttpResponse:
    parsed = urlsplit(parsed_url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {_host_header(host, port, parsed.scheme)}\r\n"
        "User-Agent: AhaDiff/0.2\r\n"
        "Accept: text/*, application/diff, application/x-patch\r\n"
        "Accept-Encoding: identity\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    try:
        sock.settimeout(_remaining_timeout(deadline))
        sock.sendall(request.encode("ascii"))
        with sock.makefile("rb") as stream:
            status_code, headers = _read_response_headers(stream, deadline=deadline)
            if status_code in _REDIRECT_STATUS_CODES:
                return _HttpResponse(
                    status_code=status_code,
                    headers=headers,
                    body=b"",
                    content_type="",
                )
            content_type = _validate_content_type(headers)
            body = _read_response_body(
                stream,
                headers,
                max_patch_bytes=max_patch_bytes,
                deadline=deadline,
            )
            return _HttpResponse(
                status_code=status_code,
                headers=headers,
                body=body,
                content_type=content_type,
            )
    except TimeoutError as exc:
        raise InputError("patch URL download timed out after 60 seconds") from exc


def _read_response_headers(stream: Any, *, deadline: float) -> tuple[int, dict[str, str]]:
    status_line = _readline(stream, deadline=deadline)
    try:
        status_parts = status_line.decode("iso-8859-1").strip().split(" ", 2)
        status_code = int(status_parts[1])
    except (IndexError, ValueError) as exc:
        raise InputError("patch URL returned an invalid HTTP status line") from exc

    headers: dict[str, str] = {}
    total_bytes = len(status_line)
    while True:
        line = _readline(stream, deadline=deadline)
        total_bytes += len(line)
        if total_bytes > _MAX_HEADER_BYTES:
            raise InputError("patch URL response headers exceed 65536 bytes")
        if line in {b"\r\n", b"\n", b""}:
            return status_code, headers
        name, separator, value = line.decode("iso-8859-1").partition(":")
        if separator:
            headers[name.strip().casefold()] = value.strip()


def _readline(stream: Any, *, deadline: float) -> bytes:
    if time.monotonic() >= deadline:
        raise TimeoutError
    line = stream.readline(_MAX_HEADER_BYTES + 1)
    if not line:
        raise InputError("patch URL returned an incomplete HTTP response")
    if len(line) > _MAX_HEADER_BYTES:
        raise InputError("patch URL response header line exceeds 65536 bytes")
    return line


def _validate_content_type(headers: Mapping[str, str]) -> str:
    raw_content_type = headers.get("content-type", "")
    content_type = raw_content_type.split(";", 1)[0].strip().casefold()
    if content_type.startswith("text/") or content_type in {
        "application/diff",
        "application/x-patch",
    }:
        return content_type
    raise InputError("patch URL content-type is not allowed")


def _read_response_body(
    stream: Any,
    headers: Mapping[str, str],
    *,
    max_patch_bytes: int,
    deadline: float,
) -> bytes:
    content_length = headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError as exc:
            raise InputError("patch URL returned invalid Content-Length") from exc
        if length > max_patch_bytes:
            raise InputError(f"patch URL exceeds {max_patch_bytes} bytes")
    if headers.get("transfer-encoding", "").casefold() == "chunked":
        return _read_chunked_body(stream, max_patch_bytes=max_patch_bytes, deadline=deadline)

    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError
        chunk = stream.read(min(_READ_CHUNK_SIZE, max_patch_bytes + 1 - total))
        if chunk == b"":
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_patch_bytes:
            raise InputError(f"patch URL exceeds {max_patch_bytes} bytes")


def _read_chunked_body(stream: Any, *, max_patch_bytes: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        size_line = _readline(stream, deadline=deadline)
        size_text = size_line.split(b";", 1)[0].strip()
        try:
            chunk_size = int(size_text, 16)
        except ValueError as exc:
            raise InputError("patch URL returned invalid chunked response") from exc
        if chunk_size == 0:
            _consume_trailers(stream, deadline=deadline)
            return b"".join(chunks)
        if time.monotonic() >= deadline:
            raise TimeoutError
        if chunk_size > max_patch_bytes - total:
            raise InputError(f"patch URL exceeds {max_patch_bytes} bytes")
        chunk = stream.read(chunk_size)
        if len(chunk) != chunk_size:
            raise InputError("patch URL returned incomplete chunked response")
        line_end = stream.read(2)
        if line_end != b"\r\n":
            raise InputError("patch URL returned invalid chunked response")
        chunks.append(chunk)
        total += len(chunk)
        if total > max_patch_bytes:
            raise InputError(f"patch URL exceeds {max_patch_bytes} bytes")


def _consume_trailers(stream: Any, *, deadline: float) -> None:
    while True:
        line = _readline(stream, deadline=deadline)
        if line in {b"\r\n", b"\n", b""}:
            return


def _port_for_url(parsed: Any) -> int:
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise InputError("patch URL has an invalid port") from exc
    if parsed_port is not None:
        return int(parsed_port)
    return 443 if parsed.scheme == "https" else 80


def _host_header(host: str, port: int, scheme: str) -> str:
    default_port = 443 if scheme == "https" else 80
    rendered_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port == default_port:
        return rendered_host
    return f"{rendered_host}:{port}"


def _remaining_timeout(deadline: float, *, cap: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    if cap is None:
        return remaining
    return min(cap, remaining)


__all__ = ["DownloadedPatch", "download_patch_url"]
