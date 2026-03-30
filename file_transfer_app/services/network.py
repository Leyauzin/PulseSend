import hashlib
import ipaddress
import socket


def recv_exact(sock: socket.socket, size: int, cancel_event=None) -> bytes:
    buffer = bytearray()

    while len(buffer) < size:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Reception annulee.")
        try:
            chunk = sock.recv(size - len(buffer))
        except socket.timeout:
            continue
        if not chunk:
            raise ConnectionError("Connexion fermee prematurement.")
        buffer.extend(chunk)

    return bytes(buffer)


def make_server_socket(port: int) -> socket.socket:
    try:
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except (AttributeError, OSError):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", port))
    server.listen(1)
    return server


def normalize_ip(ip_address: str) -> str:
    return ip_address[7:] if ip_address.startswith("::ffff:") else ip_address


def canonical_ip(ip_address: str) -> str:
    cleaned = normalize_ip(ip_address).split("%", 1)[0].strip()
    return str(ipaddress.ip_address(cleaned))


def passphrase_hash(passphrase: str) -> bytes:
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def get_local_addresses() -> list[str]:
    addresses: set[str] = set()

    try:
        host_infos = socket.getaddrinfo(socket.gethostname(), None)
    except socket.gaierror:
        host_infos = []

    for _, _, _, _, sockaddr in host_infos:
        ip_address = normalize_ip(sockaddr[0])
        if ip_address and ip_address not in {"127.0.0.1", "::1"}:
            addresses.add(ip_address)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass

    return sorted(addresses, key=lambda item: (":" in item, item))
