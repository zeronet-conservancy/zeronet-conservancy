"""Port of FileRequest.actionGetFile / handleGetFile (non-streaming path).

Business logic only -- reads real file bytes and applies the same
size/location checks and optional zlib compression as today's handler.
Site/peer bookkeeping (badAction, addPeer, cpu_time throttling) is dropped
here since it lives on the gevent Connection/Site objects that don't exist
in this trio-native package yet; that wiring lands in Phase 4 when Peer.py
and FileServer.py are rewritten on top of this.

streamFile (chunked, raw-stream transfer for large files) is deferred to
Phase 4 for the same reason -- Phase 2's job is proving the protocol-handler
pattern end-to-end, not the full transfer feature set.
"""
import os
import zlib

PROTOCOL_ID = "/zeronet/getfile/1.0.0"

FILE_BUFF = 1024 * 512

INCOMPRESSIBLE_EXTENSIONS = (
    "7z", "aac", "avi", "bz2", "flac", "gif", "gz", "jpg", "jpeg", "lz4",
    "lzma", "mkv", "mp3", "mp4", "ogg", "pdf", "png", "rar", "tgz", "txz",
    "webm", "webp", "xz", "z", "zip", "zipx", "zst",
)


def _should_compress(params):
    if params.get("compression") != "zlib":
        return False
    inner_path = params.get("inner_path", "")
    extension = inner_path.rsplit(".", 1)[-1].lower() if "." in inner_path else ""
    return extension not in INCOMPRESSIBLE_EXTENSIONS


def make_handler(site_root_resolver):
    """site_root_resolver(site_address) -> pathlib.Path | None: the on-disk
    root directory for that site, or None if the site is unknown/not serving.
    """

    async def handle(params: dict) -> dict:
        site_address = params["site"]
        inner_path = params["inner_path"]

        site_root = site_root_resolver(site_address)
        if site_root is None:
            return {"error": "Unknown site"}

        file_path = (site_root / inner_path).resolve()
        try:
            file_path.relative_to(site_root.resolve())
        except ValueError:
            return {"error": "Invalid inner_path"}

        if not file_path.is_file():
            return {"error": "File read error"}

        location = params["location"]
        read_bytes = params.get("read_bytes", FILE_BUFF)

        with open(file_path, "rb") as file:
            file_size = os.fstat(file.fileno()).st_size

            if location > file_size:
                return {"error": "Bad file location"}
            if file_size <= read_bytes and params.get("file_size") and params["file_size"] != file_size:
                return {
                    "error": "File size does not match: %sB != %sB" % (params["file_size"], file_size)
                }

            file.seek(location)
            send_size = min(read_bytes, file_size - location)
            next_location = min(location + send_size, file_size)
            body = file.read(send_size)

        if _should_compress(params) and send_size > 0:
            compressed = zlib.compress(body)
            if len(compressed) < len(body):
                return {
                    "body": compressed,
                    "size": file_size,
                    "location": next_location,
                    "compression": "zlib",
                }

        return {"body": body, "size": file_size, "location": next_location}

    return handle
