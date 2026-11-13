"""Minecraft status protocol supported by Java servers since 1.7."""
import json
import socket
import struct
from .rcon import exact


def varint(value):
    result = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def read_varint(sock):
    value = 0
    for shift in range(0,35,7):
        byte = exact(sock,1)[0]
        value |= (byte & 127) << shift
        if not byte & 128:
            return value
    raise ValueError('Invalid status varint')


def status(port):
    with socket.create_connection(('127.0.0.1',port),timeout=2) as sock:
        host = b'localhost'
        packet = b'\x00'+varint(340)+varint(len(host))+host+struct.pack('>H',port)+b'\x01'
        sock.sendall(varint(len(packet))+packet+b'\x01\x00')
        length = read_varint(sock)
        if not 0 < length < 1048576 or read_varint(sock) != 0:
            raise ValueError('Invalid status response')
        size = read_varint(sock)
        if not 0 < size < length:
            raise ValueError('Invalid status JSON size')
        result = json.loads(exact(sock,size))
        return {'version':result.get('version',{}).get('name'), 'players':result.get('players',{}), 'description':result.get('description')}
