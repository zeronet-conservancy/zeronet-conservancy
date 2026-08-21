import pathlib

from libp2p.crypto.ed25519 import Ed25519PrivateKey
from libp2p.crypto.keys import KeyPair

IDENTITY_FILENAME = "p2p_identity.key"


def load_or_create(data_dir: pathlib.Path) -> KeyPair:
    """Load the node's persistent libp2p identity from data_dir, creating one on first run.

    Storing this outside libp2p's own save_keypair()/load_keypair() (which write to a
    single fixed OS path) because zeronet-conservancy supports multiple data dirs per host.
    """
    key_path = data_dir / IDENTITY_FILENAME
    if key_path.exists():
        raw = key_path.read_bytes()
        private_key = Ed25519PrivateKey.from_bytes(raw)
    else:
        private_key = Ed25519PrivateKey.new()
        key_path.write_bytes(private_key.to_bytes())
        key_path.chmod(0o600)

    return KeyPair(private_key, private_key.get_public_key())
