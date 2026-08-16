import pytest
import io
import pathlib
import tempfile

from P2P import compat
from P2P.Site import Site
from P2P.WorkerManager import downloadBigfile

from P2P.Bigfile import (
    PieceVerificationError,
    Piecefield,
    build_piece_map,
    merkle_root,
    piece_count,
    piece_range,
    verify_piece,
)


class TestP2PBigfile:
    def testPieceRangesAndMetadata(self):
        data = b"A" * 10 + b"B" * 10 + b"C" * 3
        metadata = build_piece_map(data, piece_size=10)

        assert piece_count(len(data), 10) == 3
        assert [piece_range(len(data), 10, i) for i in range(3)] == [(0, 10), (10, 20), (20, 23)]
        assert len(metadata["sha512_pieces"]) == 3
        assert merkle_root(metadata["sha512_pieces"]) == "c9b10cf3cf857420a9dbc04867cfa3664f5b4ec23dae51c4d65e6b2a616ff757"

    def testPieceVerificationRejectsCorruption(self):
        metadata = build_piece_map(b"hello", piece_size=5)
        assert verify_piece(b"hello", metadata["sha512_pieces"][0])
        with pytest.raises(PieceVerificationError):
            verify_piece(b"hullo", metadata["sha512_pieces"][0])

    def testPiecefieldRoundTrip(self):
        field = Piecefield(5)
        field[1] = True
        field[4] = True

        restored = Piecefield.unpack(field.pack(), len(field))
        assert restored.tobytes() == b"\x00\x01\x00\x00\x01"
        assert restored.completed() == 2
        assert not restored.complete()

        restored[0] = True
        restored[2] = True
        restored[3] = True
        assert restored.complete()

    def testResumableRangedDownloadUsesPieceHashes(self):
        data = b"A" * 10 + b"B" * 10 + b"C" * 3
        metadata = build_piece_map(data, piece_size=10)
        metadata["size"] = len(data)
        metadata["sha512"] = merkle_root(metadata["sha512_pieces"])

        class Peer:
            async def getFile(self, _site, _inner_path, pos_from=0, pos_to=None):
                return io.BytesIO(data[pos_from:pos_to])

        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1BigfileTestSite", pathlib.Path(root))
                site.content_manager.contents["content.json"] = {
                    "files": {"big.bin": metadata},
                }
                await downloadBigfile(site, "big.bin", metadata, [Peer()], max_workers=2)
                assert await site.storage.read("big.bin") == data
                field = await site.storage.loadPiecefield(metadata["sha512"], 3)
                assert field.complete()

        compat.run(scenario)
