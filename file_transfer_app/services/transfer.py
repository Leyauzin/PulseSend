import os
import shutil
import socket
import time
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Callable

from file_transfer_app.models import ReceiveRequest, SendRequest
from file_transfer_app.services.network import (
    canonical_ip,
    make_server_socket,
    normalize_ip,
    passphrase_hash,
    recv_exact,
)

ProgressCallback = Callable[[float], None] | None
StatusCallback = Callable[[str], None] | None

_PROTOCOL_MAGIC = b"PSV2"
_SOCKET_BUFFER_SIZE = 16 * 1024 * 1024
_REPORT_INTERVAL_SECONDS = 0.15
_REPORT_INTERVAL_BYTES = 2 * 1024 * 1024
_SENDFILE_BLOCK_SIZE = 16 * 1024 * 1024


class _TransferReporter:
    def __init__(
        self,
        total_size: int,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        status_prefix: str,
    ):
        self.total_size = total_size
        self.progress_cb = progress_cb
        self.status_cb = status_cb
        self.status_prefix = status_prefix
        self.started_at = time.perf_counter()
        self.last_report_at = 0.0
        self.last_report_bytes = 0

    def emit(self, current_size: int, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and current_size < self.total_size:
            if now - self.last_report_at < _REPORT_INTERVAL_SECONDS:
                if current_size - self.last_report_bytes < _REPORT_INTERVAL_BYTES:
                    return

        self.last_report_at = now
        self.last_report_bytes = current_size
        progress = TransferService._progress(current_size, self.total_size)
        TransferService._notify(self.progress_cb, progress)

        elapsed = max(now - self.started_at, 1e-6)
        throughput_mbps = current_size / elapsed / (1024 * 1024)
        TransferService._notify(
            self.status_cb,
            f"{self.status_prefix}: {progress:.1f}% ({throughput_mbps:.1f} MB/s)",
        )


class TransferService:
    def send(
        self,
        request: SendRequest,
        progress_cb: ProgressCallback = None,
        status_cb: StatusCallback = None,
    ) -> None:
        source_path = request.source_path.resolve()
        if not source_path.exists():
            raise FileNotFoundError("La source selectionnee n'existe plus.")

        if source_path.is_dir():
            self._notify(status_cb, "Analyse du dossier...")
            transfer_meta = self._scan_directory(source_path)
        else:
            transfer_meta = {
                "kind": "file",
                "name": source_path.name,
                "total_size": source_path.stat().st_size,
            }

        family = socket.AF_INET6 if request.ipv6 else socket.AF_INET
        self._notify(status_cb, f"Connexion vers {request.host}:{request.port}...")

        with socket.socket(family, socket.SOCK_STREAM) as client:
            self._configure_stream_socket(client)
            client.settimeout(12.0)
            try:
                client.connect(
                    (request.host, request.port, 0, 0)
                    if request.ipv6
                    else (request.host, request.port)
                )
            except TimeoutError as error:
                raise ConnectionError(
                    "Connexion expiree. Verifiez que le poste distant a bien lance l'ecoute."
                ) from error
            except OSError as error:
                raise ConnectionError(
                    "Impossible de se connecter au poste distant. "
                    "Verifiez l'adresse IP, le port et que l'autre application ecoute bien."
                ) from error

            client.sendall(passphrase_hash(request.passphrase))
            client.sendall(_PROTOCOL_MAGIC)
            client.settimeout(None)

            if transfer_meta["kind"] == "directory":
                self._send_directory(
                    client,
                    source_path,
                    self._resolve_chunk_size(request.chunk_size, transfer_meta["total_size"], is_directory=True),
                    transfer_meta,
                    progress_cb,
                    status_cb,
                )
            else:
                self._send_file(
                    client,
                    source_path,
                    self._resolve_chunk_size(request.chunk_size, transfer_meta["total_size"], is_directory=False),
                    progress_cb,
                    status_cb,
                )

        self._notify(progress_cb, 100.0)
        self._notify(status_cb, "Transfert termine.")

    def receive(
        self,
        request: ReceiveRequest,
        progress_cb: ProgressCallback = None,
        status_cb: StatusCallback = None,
    ) -> Path:
        expected_hash = passphrase_hash(request.passphrase)
        save_directory = request.save_directory.resolve()
        save_directory.mkdir(parents=True, exist_ok=True)

        self._notify(status_cb, f"Ecoute sur le port {request.port}...")

        with closing(make_server_socket(request.port)) as server:
            server.settimeout(1.0)
            while True:
                self._raise_if_cancelled(request.cancel_event)
                try:
                    connection, address = server.accept()
                    break
                except socket.timeout:
                    continue

        remote_ip = normalize_ip(address[0])
        self._notify(status_cb, f"Connexion recue depuis {remote_ip}.")
        self._configure_stream_socket(connection)
        connection.settimeout(1.0)

        if request.allowed_ip:
            try:
                expected_ip = canonical_ip(request.allowed_ip)
                actual_ip = canonical_ip(remote_ip)
            except ValueError as error:
                connection.close()
                raise PermissionError("L'adresse IP attendue n'est pas valide.") from error

            if actual_ip != expected_ip:
                connection.close()
                raise PermissionError(
                    f"Adresse IP refusee. Attendue: {expected_ip} / Reelle: {actual_ip}."
                )

        with connection:
            if recv_exact(connection, 32, request.cancel_event) != expected_hash:
                raise PermissionError("Passphrase invalide.")

            protocol_or_length = recv_exact(connection, 4, request.cancel_event)
            if protocol_or_length == _PROTOCOL_MAGIC:
                final_path = self._receive_v2(
                    connection,
                    save_directory,
                    progress_cb,
                    status_cb,
                    request.cancel_event,
                )
            else:
                final_path = self._receive_legacy(
                    connection,
                    save_directory,
                    protocol_or_length,
                    progress_cb,
                    status_cb,
                    request.cancel_event,
                )

        self._notify(progress_cb, 100.0)
        self._notify(status_cb, "Reception terminee.")
        return final_path

    def _send_file(
        self,
        client: socket.socket,
        source_path: Path,
        chunk_size: int,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
    ) -> None:
        total_size = source_path.stat().st_size
        reporter = _TransferReporter(total_size, progress_cb, status_cb, "Envoi en cours")
        self._send_kind(client, b"F")
        self._send_text(client, source_path.name)
        client.sendall(total_size.to_bytes(8, "big"))

        sent = 0
        with source_path.open("rb") as stream:
            sent = self._stream_file(
                client,
                stream,
                total_size,
                chunk_size,
                lambda current: reporter.emit(current),
            )

        reporter.emit(sent, force=True)

    def _send_directory(
        self,
        client: socket.socket,
        source_directory: Path,
        chunk_size: int,
        transfer_meta: dict[str, object],
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
    ) -> None:
        total_size = int(transfer_meta["total_size"])
        reporter = _TransferReporter(total_size, progress_cb, status_cb, "Envoi du dossier")
        self._send_kind(client, b"D")
        self._send_text(client, source_directory.name)
        client.sendall(total_size.to_bytes(8, "big"))

        transferred = 0
        self._notify(status_cb, "Envoi du dossier sans compression...")
        for root, dir_names, file_names in os.walk(source_directory):
            root_path = Path(root)
            for dir_name in sorted(dir_names):
                directory_path = root_path / dir_name
                rel_path = directory_path.relative_to(source_directory).as_posix()
                self._send_kind(client, b"D")
                self._send_text(client, rel_path)

            for file_name in sorted(file_names):
                file_path = root_path / file_name
                relative_path = file_path.relative_to(source_directory).as_posix()
                file_size = file_path.stat().st_size

                self._send_kind(client, b"F")
                self._send_text(client, relative_path)
                client.sendall(file_size.to_bytes(8, "big"))

                with file_path.open("rb") as stream:
                    base_transferred = transferred
                    file_sent = self._stream_file(
                        client,
                        stream,
                        file_size,
                        chunk_size,
                        lambda current, base=base_transferred: reporter.emit(base + current),
                    )
                    transferred += file_sent

        self._send_kind(client, b"E")
        reporter.emit(transferred, force=True)

    def _receive_v2(
        self,
        connection: socket.socket,
        save_directory: Path,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        cancel_event=None,
    ) -> Path:
        transfer_kind = recv_exact(connection, 1, cancel_event)
        if transfer_kind == b"F":
            return self._receive_v2_file(
                connection, save_directory, progress_cb, status_cb, cancel_event
            )
        if transfer_kind == b"D":
            return self._receive_v2_directory(
                connection, save_directory, progress_cb, status_cb, cancel_event
            )
        raise ConnectionError("Type de transfert inconnu.")

    def _receive_v2_file(
        self,
        connection: socket.socket,
        save_directory: Path,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        cancel_event=None,
    ) -> Path:
        filename = self._recv_text(connection, cancel_event)
        total_size = int.from_bytes(recv_exact(connection, 8, cancel_event), "big")
        save_path = save_directory / Path(filename).name
        reporter = _TransferReporter(total_size, progress_cb, status_cb, "Reception en cours")

        try:
            received = self._receive_file_bytes(
                connection,
                save_path,
                total_size,
                reporter.emit,
                cancel_event=cancel_event,
            )
            if received != total_size:
                raise ConnectionError("Le transfert a ete interrompu avant la fin.")
            reporter.emit(received, force=True)
            return save_path
        except InterruptedError:
            if save_path.exists():
                save_path.unlink()
            raise

    def _receive_v2_directory(
        self,
        connection: socket.socket,
        save_directory: Path,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        cancel_event=None,
    ) -> Path:
        root_name = self._recv_text(connection, cancel_event)
        total_size = int.from_bytes(recv_exact(connection, 8, cancel_event), "big")
        root_path = save_directory / Path(root_name).name
        root_path.mkdir(parents=True, exist_ok=True)

        received = 0
        reporter = _TransferReporter(total_size, progress_cb, status_cb, "Reception du dossier")
        self._notify(status_cb, "Reception du dossier sans compression...")
        try:
            while True:
                self._raise_if_cancelled(cancel_event)
                entry_kind = recv_exact(connection, 1, cancel_event)
                if entry_kind == b"E":
                    break

                relative_path = self._safe_relative_path(self._recv_text(connection, cancel_event))
                target_path = root_path / relative_path

                if entry_kind == b"D":
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                if entry_kind != b"F":
                    raise ConnectionError("Entree de dossier invalide recue.")

                file_size = int.from_bytes(recv_exact(connection, 8, cancel_event), "big")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                base_received = received
                file_received = self._receive_file_bytes(
                    connection,
                    target_path,
                    file_size,
                    lambda current, base=base_received: reporter.emit(base + current),
                    cancel_event=cancel_event,
                )
                received = base_received + file_received

            if received != total_size:
                raise ConnectionError("Le transfert du dossier a ete interrompu avant la fin.")

            reporter.emit(received, force=True)
            return root_path
        except InterruptedError:
            shutil.rmtree(root_path, ignore_errors=True)
            raise

    def _receive_legacy(
        self,
        connection: socket.socket,
        save_directory: Path,
        initial_length_bytes: bytes,
        progress_cb: ProgressCallback,
        status_cb: StatusCallback,
        cancel_event=None,
    ) -> Path:
        name_length = int.from_bytes(initial_length_bytes, "big")
        raw_name = recv_exact(connection, name_length, cancel_event).decode("utf-8")
        total_size = int.from_bytes(recv_exact(connection, 8, cancel_event), "big")

        is_directory = raw_name.startswith("__DIR__:")
        target_name = raw_name[8:] if is_directory else raw_name
        save_path = save_directory / Path(target_name).name

        try:
            received = self._receive_file_bytes(
                connection,
                save_path,
                total_size,
                _TransferReporter(total_size, progress_cb, status_cb, "Reception en cours").emit,
                cancel_event=cancel_event,
            )
            if received != total_size:
                raise ConnectionError("Le transfert a ete interrompu avant la fin.")
        except InterruptedError:
            if save_path.exists():
                save_path.unlink()
            raise

        if is_directory:
            raise ConnectionError(
                "Le format dossier compresse des anciennes versions n'est plus pris en charge ici."
            )
        return save_path

    def _receive_file_bytes(
        self,
        connection: socket.socket,
        save_path: Path,
        total_size: int,
        report_cb: Callable[[int], None],
        cancel_event=None,
    ) -> int:
        received = 0
        recv_block_size = self._resolve_chunk_size(0, total_size, is_directory=False)
        with save_path.open("wb") as stream:
            while received < total_size:
                self._raise_if_cancelled(cancel_event)
                remaining = total_size - received
                try:
                    chunk = connection.recv(min(recv_block_size, remaining))
                except socket.timeout:
                    continue
                if not chunk:
                    break

                stream.write(chunk)
                received += len(chunk)
                report_cb(received)

        return received

    @staticmethod
    def _stream_file(
        client: socket.socket,
        stream,
        total_size: int,
        chunk_size: int,
        progress_hook: Callable[[int], None] | None = None,
    ) -> int:
        if hasattr(client, "sendfile"):
            sent = 0
            while sent < total_size:
                count = min(_SENDFILE_BLOCK_SIZE, total_size - sent)
                try:
                    transferred = client.sendfile(stream, offset=sent, count=count)
                except (AttributeError, OSError):
                    break
                if transferred is None:
                    transferred = count
                if transferred <= 0:
                    break
                sent += transferred
                if progress_hook is not None:
                    progress_hook(sent)
            if sent == total_size:
                return sent
            stream.seek(sent)

        sent = stream.tell()
        while chunk := stream.read(chunk_size):
            client.sendall(chunk)
            sent += len(chunk)
            if progress_hook is not None:
                progress_hook(sent)
        return sent

    @staticmethod
    def _scan_directory(source_directory: Path) -> dict[str, object]:
        total_size = 0
        for root, _, file_names in os.walk(source_directory):
            root_path = Path(root)
            for file_name in file_names:
                total_size += (root_path / file_name).stat().st_size

        return {
            "kind": "directory",
            "name": source_directory.name,
            "total_size": total_size,
        }

    @staticmethod
    def _resolve_chunk_size(selected_chunk_size: int, total_size: int, is_directory: bool) -> int:
        if selected_chunk_size > 0:
            return selected_chunk_size

        if total_size <= 32 * 1024 * 1024:
            return 512 * 1024
        if total_size <= 512 * 1024 * 1024:
            return 2 * 1024 * 1024
        if total_size <= 8 * 1024 * 1024 * 1024:
            return 8 * 1024 * 1024
        if is_directory:
            return 8 * 1024 * 1024
        return 16 * 1024 * 1024

    @staticmethod
    def _configure_stream_socket(sock: socket.socket) -> None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, _SOCKET_BUFFER_SIZE)
        except OSError:
            pass

        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _SOCKET_BUFFER_SIZE)
        except OSError:
            pass

    @staticmethod
    def _send_kind(client: socket.socket, value: bytes) -> None:
        client.sendall(value)

    @staticmethod
    def _send_text(client: socket.socket, value: str) -> None:
        data = value.encode("utf-8")
        client.sendall(len(data).to_bytes(4, "big"))
        client.sendall(data)

    @staticmethod
    def _recv_text(connection: socket.socket, cancel_event=None) -> str:
        size = int.from_bytes(recv_exact(connection, 4, cancel_event), "big")
        return recv_exact(connection, size, cancel_event).decode("utf-8")

    @staticmethod
    def _safe_relative_path(raw_path: str) -> Path:
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise PermissionError("Chemin de fichier recu invalide.")
        return Path(*relative.parts)

    @staticmethod
    def _progress(current: int, total: int) -> float:
        if total <= 0:
            return 100.0
        return min(100.0, current / total * 100)

    @staticmethod
    def _notify(callback: Callable | None, value) -> None:
        if callback is not None:
            callback(value)

    @staticmethod
    def _raise_if_cancelled(cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Reception annulee.")


def send_logic(
    path,
    host,
    port,
    ipv6,
    chunk_size,
    passphrase,
    progress_cb,
    status_cb,
) -> None:
    request = SendRequest(
        source_path=Path(path),
        host=host,
        port=port,
        ipv6=ipv6,
        chunk_size=chunk_size,
        passphrase=passphrase,
    )
    TransferService().send(request, progress_cb=progress_cb, status_cb=status_cb)


def recv_logic(
    port,
    allowed_ip,
    passphrase,
    progress_cb,
    status_cb,
    save_directory=None,
) -> Path:
    request = ReceiveRequest(
        port=port,
        allowed_ip=allowed_ip,
        passphrase=passphrase,
        save_directory=Path(save_directory) if save_directory else Path.cwd(),
    )
    return TransferService().receive(request, progress_cb=progress_cb, status_cb=status_cb)
