"""Native Bigfile primitives.

The legacy Bigfile plugin stores one truncated SHA-512 digest per piece in a
msgpack piecemap and tracks downloaded pieces as a byte-per-piece field.  This
module keeps that wire/storage format while making the safety-critical parts
independent of the old gevent site and worker classes.
"""
import array
import hashlib
import math

from util import Msgpack


DEFAULT_PIECE_SIZE = 1024 * 1024


class BigfileError(Exception):
    pass


class PieceVerificationError(BigfileError):
    pass


def piece_count(size: int, piece_size: int) -> int:
    if size < 0 or piece_size <= 0:
        raise ValueError("size must be non-negative and piece_size must be positive")
    return math.ceil(size / piece_size) if size else 0


def piece_range(size: int, piece_size: int, piece_index: int) -> tuple[int, int]:
    count = piece_count(size, piece_size)
    if piece_index < 0 or piece_index >= count:
        raise IndexError("piece index out of range: %s" % piece_index)
    start = piece_index * piece_size
    return start, min(size, start + piece_size)


def digest_piece(data: bytes) -> bytes:
    """Return the same 256-bit truncated SHA-512 digest as CryptHash."""
    return hashlib.sha512(data).digest()[:32]


def build_piece_map(data: bytes, piece_size: int = DEFAULT_PIECE_SIZE) -> dict:
    """Build canonical Bigfile piece metadata for a complete byte string."""
    if piece_size <= 0:
        raise ValueError("piece_size must be positive")
    pieces = [digest_piece(data[pos:pos + piece_size]) for pos in range(0, len(data), piece_size)]
    return {"sha512_pieces": pieces, "piece_size": piece_size}


def merkle_root(piece_hashes: list[bytes]) -> str:
    """Calculate the legacy Bigfile Merkle root from piece digests."""
    if not piece_hashes:
        return digest_piece(b"").hex()
    level = list(piece_hashes)
    while len(level) > 1:
        next_level = [
            digest_piece(level[pos] + level[pos + 1])
            for pos in range(0, len(level) - 1, 2)
        ]
        if len(level) % 2:
            next_level.append(level[-1])
        level = next_level
    return level[0].hex()


def verify_piece(piece: bytes, expected: bytes | str) -> bool:
    expected_bytes = bytes.fromhex(expected) if isinstance(expected, str) else expected
    if digest_piece(piece) != expected_bytes:
        raise PieceVerificationError("Invalid Bigfile piece hash")
    return True


def load_piecemap(data: bytes, file_name: str | None = None) -> dict:
    """Decode a legacy msgpack piecemap and return one file's metadata."""
    decoded = Msgpack.unpack(data)
    if file_name is None:
        if len(decoded) != 1:
            raise BigfileError("Piecemap contains multiple files; file_name is required")
        decoded = next(iter(decoded.values()))
    else:
        if file_name not in decoded:
            raise BigfileError("Piecemap has no entry for %s" % file_name)
        decoded = decoded[file_name]
    hashes = decoded.get("sha512_pieces")
    if not isinstance(hashes, list) or not hashes:
        raise BigfileError("Piecemap has no piece hashes")
    decoded = dict(decoded)
    decoded["sha512_pieces"] = hashes
    return decoded


class Piecefield:
    """Persistent, byte-per-piece completion state."""

    def __init__(self, count: int, data: bytes | bytearray | None = None):
        if count < 0:
            raise ValueError("piece count must be non-negative")
        self._data = bytearray(data or b"\x00" * count)
        if len(self._data) != count:
            raise ValueError("piecefield length does not match piece count")

    def __len__(self):
        return len(self._data)

    def __getitem__(self, index: int) -> bool:
        return bool(self._data[index])

    def __setitem__(self, index: int, value: bool) -> None:
        self._data[index] = 1 if value else 0

    def completed(self) -> int:
        return sum(self._data)

    def complete(self) -> bool:
        return bool(self._data) and all(self._data)

    def tobytes(self) -> bytes:
        return bytes(self._data)

    def pack(self) -> bytes:
        """Run-length encode using the legacy Bigfile piecefield format."""
        if not self._data:
            return b""
        runs = [0] if self._data[0] == 0 else []
        current = self._data[0]
        length = 0
        for value in self._data:
            if value != current:
                runs.append(length)
                current = value
                length = 0
            length += 1
        runs.append(length)
        return array.array("H", runs).tobytes()

    @classmethod
    def unpack(cls, packed: bytes, count: int) -> "Piecefield":
        if not packed:
            return cls(count)
        runs = array.array("H", packed)
        values = bytearray()
        value = 1
        for run in runs:
            if run > 10000:
                raise BigfileError("Invalid packed piecefield run")
            values.extend(bytes([value]) * run)
            value = 0 if value else 1
        if len(values) != count:
            raise BigfileError("Packed piecefield length does not match piece count")
        return cls(count, values)

    def to_json(self) -> dict:
        return {"count": len(self), "data": self.tobytes().hex()}

    @classmethod
    def from_json(cls, value: dict) -> "Piecefield":
        return cls(int(value["count"]), bytes.fromhex(value["data"]))


def validate_file_info(file_info: dict) -> tuple[int, int, list]:
    size = int(file_info["size"])
    piece_size = int(file_info["piece_size"])
    hashes = file_info.get("sha512_pieces")
    if hashes is None:
        raise BigfileError("File info does not contain piece hashes")
    count = piece_count(size, piece_size)
    if len(hashes) != count:
        raise BigfileError("Piece hash count does not match file size")
    return size, piece_size, hashes
