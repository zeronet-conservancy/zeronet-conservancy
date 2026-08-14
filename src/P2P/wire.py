"""Shared msgpack request/response envelope for P2P protocol streams.

Replaces Connection.py's length-prefixed streaming unpacker + handshake with
a much simpler scheme: libp2p already frames/multiplexes/authenticates the
connection, so each protocol stream just needs an explicit 4-byte length
prefix around one msgpack-encoded dict per message. One stream per request
in Phase 2 (see plan section 4) -- req_id correlation is dropped since each
stream already isolates one request/response pair.
"""
from util import Msgpack

MAX_MSG_SIZE = 10 * 1024 * 1024
_LEN_PREFIX_SIZE = 4


async def _read_exact(stream, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = await stream.read(remaining)
        if not chunk:
            raise ConnectionError("stream closed while reading %d more bytes" % remaining)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


async def write_msg(stream, msg: dict) -> None:
    data = Msgpack.pack(msg)
    if len(data) > MAX_MSG_SIZE:
        raise ValueError("message too large: %d bytes" % len(data))
    await stream.write(len(data).to_bytes(_LEN_PREFIX_SIZE, "big"))
    await stream.write(data)


async def read_msg(stream) -> dict:
    size = int.from_bytes(await _read_exact(stream, _LEN_PREFIX_SIZE), "big")
    if size > MAX_MSG_SIZE:
        raise ValueError("incoming message too large: %d bytes" % size)
    data = await _read_exact(stream, size)
    return Msgpack.unpack(data, decode=False)


async def request(stream, params: dict) -> dict:
    """Client side: send params, wait for the single response message."""
    await write_msg(stream, params)
    return await read_msg(stream)


async def respond(stream, msg) -> None:
    """Server side: send the (single) response message for this stream."""
    if not isinstance(msg, dict):
        msg = {"body": msg}
    await write_msg(stream, msg)
