import json
import socket
import threading
import logging
import os
import platform

log = logging.getLogger("jarvis.ipc")

SYSTEM = platform.system()


class IPCServer:
    """IPC server for pushing state to the HUD process.
    Uses Unix sockets on macOS, named pipes on Windows.
    """

    def __init__(self, socket_path):
        self.socket_path = socket_path
        self._server = None
        self._clients: list = []
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        if SYSTEM == "Windows":
            self._start_named_pipe()
        else:
            self._start_unix_socket()

    # ── Unix socket (macOS / Linux) ─────────────────────────────

    def _start_unix_socket(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(2)
        self._server.settimeout(1.0)
        self._running = True

        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()
        log.info(f"IPC server listening on {self.socket_path}")

    def _accept_loop(self):
        while self._running:
            try:
                client, _ = self._server.accept()
                with self._lock:
                    self._clients.append(client)
                log.info("HUD client connected")
            except socket.timeout:
                continue
            except OSError:
                break

    # ── Named pipe (Windows) ────────────────────────────────────

    def _start_named_pipe(self):
        import win32pipe
        import win32file

        self._running = True
        thread = threading.Thread(
            target=self._pipe_accept_loop, daemon=True
        )
        thread.start()
        log.info(f"IPC server listening on {self.socket_path}")

    def _pipe_accept_loop(self):
        import win32pipe
        import win32file
        import pywintypes

        while self._running:
            try:
                pipe = win32pipe.CreateNamedPipe(
                    self.socket_path,
                    win32pipe.PIPE_ACCESS_OUTBOUND,
                    (
                        win32pipe.PIPE_TYPE_BYTE
                        | win32pipe.PIPE_READMODE_BYTE
                        | win32pipe.PIPE_WAIT
                    ),
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536,
                    65536,
                    0,
                    None,
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                with self._lock:
                    self._clients.append(pipe)
                log.info("HUD client connected (named pipe)")
            except pywintypes.error:
                break

    # ── Broadcast ───────────────────────────────────────────────

    def broadcast(self, message):
        """Send a JSON message to all connected HUD clients."""
        data = json.dumps(message).encode("utf-8") + b"\n"

        with self._lock:
            dead = []
            for client in self._clients:
                try:
                    if SYSTEM == "Windows":
                        import win32file
                        win32file.WriteFile(client, data)
                    else:
                        client.sendall(data)
                except (BrokenPipeError, OSError):
                    dead.append(client)
                except Exception:
                    dead.append(client)

            for client in dead:
                self._clients.remove(client)
                try:
                    if SYSTEM == "Windows":
                        import win32file
                        win32file.CloseHandle(client)
                    else:
                        client.close()
                except OSError:
                    pass

    def stop(self):
        self._running = False
        with self._lock:
            for client in self._clients:
                try:
                    if SYSTEM == "Windows":
                        import win32file
                        win32file.CloseHandle(client)
                    else:
                        client.close()
                except OSError:
                    pass
            self._clients.clear()

        if self._server:
            self._server.close()

        if SYSTEM != "Windows" and os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        log.info("IPC server stopped")
