"""Port of FileRequest.actionGetFile / handleGetFile (non-streaming path).

Business logic only -- reads real file bytes and applies the same
size/location checks and optional zlib compression as today's handler.
Site/peer bookkeeping (badAction, addPeer, cpu_time throttling) is dropped
here since it lives on the Peer/ConnectionPolicy objects Phase 6 is
building elsewhere.

File access goes through SiteStorage (readChunk()) rather than opening the
file directly: SiteStorage.getPath() applies the real traversal-safety
check (Phase 6), and the actual disk read is offloaded to SiteStorage's
thread pool instead of blocking the trio event loop -- this handler used
to open()/read() the file inline, which was a real gap fixed here.

streamFile (chunked, raw-stream transfer for large files) is still
deferred -- Phase 2's job was proving the protocol-handler pattern
end-to-end, not the full transfer feature set.
"""
import zlib

from ..SiteStorage import AccessError

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


def make_handler(site_storage_resolver):
    """site_storage_resolver(site_address) -> SiteStorage | None: the
    storage for that site, or None if the site is unknown/not serving.
    """

    async def handle(params: dict) -> dict:
        site_address = params["site"]
        inner_path = params["inner_path"]

        storage = site_storage_resolver(site_address)
        if storage is None:
            return {"error": "Unknown site"}

        location = params["location"]
        read_bytes = params.get("read_bytes", FILE_BUFF)

        try:
            if not storage.isFile(inner_path):
                return {"error": "File read error"}
            body, file_size = await storage.readChunk(inner_path, location, read_bytes)
        except AccessError:
            return {"error": "Invalid inner_path"}
        except OSError:
            return {"error": "File read error"}

        if location > file_size:
            return {"error": "Bad file location"}
        if file_size <= read_bytes and params.get("file_size") and params["file_size"] != file_size:
            return {
                "error": "File size does not match: %sB != %sB" % (params["file_size"], file_size)
            }

        send_size = len(body)
        next_location = min(location + send_size, file_size)

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
