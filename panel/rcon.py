"""Bounded Source RCON client; supports legacy Minecraft packet framing."""
import socket
import struct


def exact(sock, length):
    result = b''
    while len(result) < length:
        part = sock.recv(length - len(result))
        if not part:
            raise ConnectionError('RCON connection closed')
        result += part
    return result


def receive(sock):
    length, = struct.unpack('<i', exact(sock, 4))
    if not 10 <= length <= 4 * 1024 * 1024:
        raise ValueError('Invalid RCON packet length')
    data = exact(sock, length)
    if data[-2:] != b'\0\0':
        raise ValueError('Invalid RCON terminator')
    ident, kind = struct.unpack('<ii', data[:8])
    return ident, kind, data[8:-2]


def send(sock, ident, kind, text):
    body = struct.pack('<ii', ident, kind) + text.encode('utf-8') + b'\0\0'
    sock.sendall(struct.pack('<i', len(body)) + body)


def command(port, password, text):
    if not password:
        raise ValueError('RCON is not configured')
    if not text or len(text.encode()) > 1400 or any(c in text for c in '\r\n\0'):
        raise ValueError('Command must be one line, at most 1400 bytes')
    with socket.create_connection(('127.0.0.1', port), timeout=4) as sock:
        send(sock, 101, 3, password)
        for _ in range(3):
            ident, kind, _ = receive(sock)
            if ident == -1:
                raise PermissionError('RCON authentication failed')
            if ident == 101 and kind == 2:
                break
        else:
            raise ConnectionError('Missing RCON authentication response')
        send(sock, 102, 2, text)
        # Minecraft handles commands synchronously. A second command is a barrier,
        # avoiding timeout-based truncation and working on 1.12.2 implementations.
        send(sock, 103, 2, '')
        chunks = []
        total = 0
        while True:
            ident, kind, body = receive(sock)
            if ident == 103:
                break
            if ident != 102 or kind != 0:
                raise ConnectionError('Unexpected RCON response')
            total += len(body)
            if total > 4 * 1024 * 1024:
                raise ValueError('RCON response exceeds limit')
            chunks.append(body)
        return b''.join(chunks).decode('utf-8', errors='replace')
