import hashlib
import logging
import json
import re
import time

from Config import config
from Plugin import PluginManager

import ssl
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

try:
    import certifi
    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = ssl.create_default_context()

allow_reload = False

log = logging.getLogger("XidResolverPlugin")

# In-memory cache: identity_address -> {name, tld, owner, active, revoked_at, cached_at}
_identity_cache = {}

# How long to cache positive results (seconds)
IDENTITY_CACHE_TTL = 300  # 5 minutes
# How long to cache negative (not found) results
NEGATIVE_CACHE_TTL = 60  # 1 minute
# Grace period (seconds) for clock drift between chain block time and content modified timestamp.
# Content modified within this window after revocation is still accepted.
REVOCATION_GRACE_PERIOD = 60  # 1 minute

# ---------------------------------------------------------------------------
# Chain attestation verification for xID resolution
# ---------------------------------------------------------------------------
# State digest cache: {digest, height, timestamp}
_digest_cache = {"digest": None, "height": 0, "timestamp": 0}
# Attestation finalization cache: digest -> {finalized, timestamp}
_attestation_cache = {}

DIGEST_CACHE_TTL = 15  # seconds
ATTESTATION_CACHE_TTL = 30  # seconds


def _fetch_state_digest(rpc_url):
    """Fetch the current xID state digest from the chain."""
    now = time.time()
    if _digest_cache["digest"] and (now - _digest_cache["timestamp"]) < DIGEST_CACHE_TTL:
        return _digest_cache

    data = _fetch_json("%s/xid/v1/state_digest" % rpc_url)
    if data and data.get("digest"):
        _digest_cache["digest"] = data["digest"]
        _digest_cache["height"] = int(data.get("height", 0))
        _digest_cache["timestamp"] = now
        return _digest_cache
    return None


def _is_digest_finalized(rpc_url, digest):
    """Check if a state digest has been attested by 2/3+ validators."""
    now = time.time()
    cached = _attestation_cache.get(digest)
    if cached and (now - cached["timestamp"]) < ATTESTATION_CACHE_TTL:
        return cached["finalized"]

    data = _fetch_json("%s/xid/v1/attestations?digest=%s" % (rpc_url, digest))
    if data is not None:
        finalized = bool(data.get("finalized", False))
        _attestation_cache[digest] = {"finalized": finalized, "timestamp": now}
        return finalized

    return False


def _verify_merkle_proof(leaf_hash, leaf_index, siblings, expected_root):
    """Verify a Merkle inclusion proof by recomputing the root from leaf to top.

    Args:
        leaf_hash: hex string of the leaf hash
        leaf_index: integer position of the leaf
        siblings: list of hex string sibling hashes (bottom to top)
        expected_root: hex string of the expected root hash

    Returns:
        True if the recomputed root matches expected_root
    """
    current = bytes.fromhex(leaf_hash)
    idx = leaf_index

    for sibling_hex in siblings:
        sibling = bytes.fromhex(sibling_hex)
        if idx % 2 == 0:
            # Current is left child, sibling is right
            combined = current + sibling
        else:
            # Current is right child, sibling is left
            combined = sibling + current
        current = hashlib.sha256(combined).digest()
        idx //= 2

    recomputed_root = current.hex()
    return recomputed_root == expected_root


def _resolve_with_proof(rpc_url, tld, name):
    """Resolve an xID name using the resolve_with_proof endpoint and verify
    the Merkle proof against an attested state digest.

    Returns (domain_data, verified) where domain_data is the DomainSnapshot dict
    and verified is True if the proof was cryptographically verified against a
    finalized state digest.

    Returns (None, False) if the name is not found.
    """
    data = _fetch_json("%s/xid/v1/resolve_with_proof/%s/%s" % (rpc_url, tld, name))
    if not data or not data.get("domain"):
        return None, False

    domain = data["domain"]
    proof = data.get("proof", {})
    chain_root = data.get("root", "")

    # Extract proof components
    leaf_hash = proof.get("leaf_hash", "")
    leaf_index = int(proof.get("leaf_index", 0))
    siblings = proof.get("siblings", [])
    proof_root = proof.get("root", "")

    if not leaf_hash or not proof_root:
        log.warning("resolve_with_proof returned incomplete proof for %s.%s" % (name, tld))
        return domain, False

    # Step 1: Verify the Merkle proof (leaf -> siblings -> root)
    if not _verify_merkle_proof(leaf_hash, leaf_index, siblings, proof_root):
        log.error(
            "Merkle proof verification FAILED for %s.%s: "
            "recomputed root does not match proof root %s..." % (name, tld, proof_root[:16])
        )
        return None, False

    # Step 2: Verify the proof root matches the chain's state digest
    if proof_root != chain_root:
        log.warning(
            "Proof root %s... != chain root %s... for %s.%s" %
            (proof_root[:16], chain_root[:16], name, tld)
        )

    # Step 3: Verify the state digest is finalized (attested by 2/3+ validators)
    digest_info = _fetch_state_digest(rpc_url)
    if not digest_info:
        log.warning("Could not fetch state digest for attestation check")
        return domain, False

    attested_digest = digest_info["digest"]

    # The proof root must match the current attested state digest
    if proof_root != attested_digest:
        log.warning(
            "Proof root %s... does not match attested digest %s... for %s.%s" %
            (proof_root[:16], attested_digest[:16], name, tld)
        )
        return domain, False

    if not _is_digest_finalized(rpc_url, attested_digest):
        log.warning(
            "State digest %s... not yet finalized (awaiting 2/3+ validator attestation)" %
            attested_digest[:16]
        )
        return domain, False

    log.debug(
        "xID %s.%s verified: Merkle proof valid, digest %s... finalized at height %s" %
        (name, tld, attested_digest[:16], digest_info.get("height", "?"))
    )
    return domain, True


def _get_rpc_url():
    """Get the xID REST API base URL."""
    return getattr(config, "xid_rpc_url", "https://api.testnet.epix.zone").rstrip("/")


def _fetch_json(url, timeout=10):
    """Fetch JSON from a URL, return parsed dict or None on error."""
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        resp = urlopen(req, timeout=timeout, context=_ssl_context)
        return json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, IOError) as e:
        log.debug("xID RPC fetch failed for %s: %s" % (url, e))
        return None


def resolve_identity_xid(identity_address):
    """Resolve a linked identity address to its xID name.

    Uses reverse lookup to find the name, then cross-verifies via
    resolve_with_proof to ensure the data is attested by 2/3+ validators.

    Returns dict with {name, tld, owner, active, revoked_at, revoked_at_time} or None if not found.
    Results are cached with TTL to avoid repeated API calls.
    """
    now = time.time()

    # Check cache
    cached = _identity_cache.get(identity_address)
    if cached:
        ttl = IDENTITY_CACHE_TTL if cached.get("name") else NEGATIVE_CACHE_TTL
        if (now - cached["cached_at"]) < ttl:
            if cached.get("name"):
                return {
                    "name": cached["name"],
                    "tld": cached["tld"],
                    "owner": cached["owner"],
                    "active": cached["active"],
                    "revoked_at": cached["revoked_at"],
                    "revoked_at_time": cached.get("revoked_at_time", 0),
                    "avatar": cached.get("avatar", ""),
                    "bio": cached.get("bio", ""),
                }
            return None

    # Cache miss — query the chain via reverse lookup
    rpc_url = _get_rpc_url()
    data = _fetch_json("%s/xid/v1/reverse_identity/%s" % (rpc_url, identity_address))

    if data and data.get("name_record"):
        record = data["name_record"]
        name = record.get("name", "")
        tld = record.get("tld", "")

        if not name or not tld:
            _identity_cache[identity_address] = {"name": None, "cached_at": now}
            return None

        # Cross-verify: use resolve_with_proof to get chain-attested data
        domain, verified = _resolve_with_proof(rpc_url, tld, name)
        if not domain or not verified:
            log.error(
                "SECURITY: Reverse lookup for %s returned %s.%s but proof verification "
                "failed. Rejecting to prevent rogue RPC attacks." % (identity_address, name, tld)
            )
            _identity_cache[identity_address] = {"name": None, "cached_at": now}
            return None

        # Find this identity in the verified domain data
        identity_info = None
        for ident in domain.get("identities", []):
            if ident.get("address") == identity_address:
                identity_info = ident
                break

        if not identity_info:
            log.warning(
                "Reverse lookup said %s belongs to %s.%s but verified domain data "
                "does not contain this identity" % (identity_address, name, tld)
            )
            _identity_cache[identity_address] = {"name": None, "cached_at": now}
            return None

        # Extract profile from verified domain snapshot
        avatar = ""
        bio = ""
        profile = domain.get("profile")
        if profile:
            avatar = profile.get("avatar", "")
            bio = profile.get("bio", "")

        verified_record = domain.get("record", {})
        entry = {
            "name": name,
            "tld": tld,
            "owner": verified_record.get("owner", ""),
            "active": identity_info.get("active", True),
            "revoked_at": int(identity_info.get("revoked_at", 0)),
            "revoked_at_time": int(identity_info.get("revoked_at_time", 0)),
            "avatar": avatar,
            "bio": bio,
            "cached_at": now,
        }
        _identity_cache[identity_address] = entry
        return {
            "name": entry["name"],
            "tld": entry["tld"],
            "owner": entry["owner"],
            "active": entry["active"],
            "revoked_at": entry["revoked_at"],
            "revoked_at_time": entry["revoked_at_time"],
            "avatar": entry["avatar"],
            "bio": entry["bio"],
        }
    else:
        # Negative cache
        _identity_cache[identity_address] = {"name": None, "cached_at": now}
        return None


def invalidate_identity_cache(identity_address=None):
    """Invalidate cache for a specific identity or all identities."""
    if identity_address:
        _identity_cache.pop(identity_address, None)
    else:
        _identity_cache.clear()


# Cache for xID name resolution: "name.tld" -> {owner, identities, cached_at}
_xid_name_cache = {}
XID_NAME_CACHE_TTL = 300  # 5 minutes


def resolve_xid_name(name, tld="epix"):
    """Resolve an xID name to its owner address and linked identities.

    Uses the resolve_with_proof endpoint and verifies the response against a
    Merkle proof and finalized state digest (attested by 2/3+ validators).
    This prevents a rogue RPC from returning fabricated identity data.

    Returns dict {owner: str, identities: [{address, active, revoked_at_time}, ...]}
    or None if not found.  Both active and revoked identities are included so that
    callers can perform temporal verification (accept old content signed before
    revocation).
    """
    cache_key = "%s.%s" % (name, tld)
    now = time.time()

    cached = _xid_name_cache.get(cache_key)
    if cached and (now - cached["cached_at"]) < XID_NAME_CACHE_TTL:
        if cached.get("owner"):
            return {"owner": cached["owner"], "identities": cached["identities"]}
        return None

    rpc_url = _get_rpc_url()

    # Use resolve_with_proof for chain-verified resolution
    domain, verified = _resolve_with_proof(rpc_url, tld, name)
    if not domain:
        _xid_name_cache[cache_key] = {"owner": None, "cached_at": now}
        return None

    if not verified:
        log.error(
            "SECURITY: xID resolution for %s.%s could not be verified against chain. "
            "Rejecting unverified data to prevent rogue RPC attacks." % (name, tld)
        )
        return None

    # Extract owner from the domain record
    record = domain.get("record", {})
    owner = record.get("owner", "")

    # Extract identities from the verified domain snapshot
    identities = []
    for p in domain.get("identities", []):
        identities.append({
            "address": p.get("address", ""),
            "active": p.get("active", False),
            "revoked_at_time": int(p.get("revoked_at_time", 0)),
        })

    _xid_name_cache[cache_key] = {
        "owner": owner,
        "identities": identities,
        "cached_at": now,
    }
    return {"owner": owner, "identities": identities}


def invalidate_xid_name_cache(name=None):
    """Invalidate xID name resolution cache."""
    if name:
        _xid_name_cache.pop(name, None)
    else:
        _xid_name_cache.clear()


# Cache for site-level xID resolution: site_address -> {name, tld, verified, cached_at}
_site_xid_cache = {}
SITE_XID_CACHE_TTL = 300  # 5 minutes


def resolve_site_xid(site):
    """Resolve a site's canonical xID name from its content.json xid_name claim.

    The site owner declares their canonical name by setting "xid_name" in
    content.json (e.g. "mysite.epix").  This function verifies the claim by
    doing a forward lookup on-chain: the xID DNS record for that name must
    include an EpixNet site record pointing back to this site's address.

    Returns dict {name, tld, verified} or None if no claim or verification fails.
    """
    site_address = site.address
    now = time.time()

    # Check cache
    cached = _site_xid_cache.get(site_address)
    if cached and (now - cached["cached_at"]) < SITE_XID_CACHE_TTL:
        if cached.get("name"):
            return {
                "name": cached["name"],
                "tld": cached["tld"],
                "verified": cached["verified"],
            }
        return None

    # Read the site's content.json for the domain claim
    content = site.content_manager.contents.get("content.json", {})
    xid_name_claim = content.get("domain", "").strip()

    if not xid_name_claim:
        _site_xid_cache[site_address] = {"name": None, "cached_at": now}
        return None

    # Parse "name.tld" format
    parts = xid_name_claim.rsplit(".", 1)
    if len(parts) != 2:
        log.warning("Invalid xid_name format in content.json: %s" % xid_name_claim)
        _site_xid_cache[site_address] = {"name": None, "cached_at": now}
        return None

    name, tld = parts

    # Forward lookup: resolve the xID name on-chain
    xid_info = resolve_xid_name(name, tld)
    if not xid_info:
        log.warning(
            "Site %s claims xid_name '%s' but name not found on chain" %
            (site_address, xid_name_claim)
        )
        _site_xid_cache[site_address] = {"name": None, "cached_at": now}
        return None

    # Verify: the xID must have a DNS record pointing to this site address.
    # Check the domain's DNS records for an EpixNet site record matching
    # this site's address, OR check if any linked identity's address matches
    # the site address (for sites owned directly by the xID owner).
    rpc_url = _get_rpc_url()
    domain, verified = _resolve_with_proof(rpc_url, tld, name)

    if not domain or not verified:
        log.warning(
            "Site %s claims xid_name '%s' but chain verification failed" %
            (site_address, xid_name_claim)
        )
        _site_xid_cache[site_address] = {"name": None, "cached_at": now}
        return None

    # Check DNS records for an EpixNet site record pointing to this address
    dns_match = False
    for dns_record in domain.get("dns_records", []):
        value = dns_record.get("value", "")
        # EpixNet site DNS record: value is the site address
        if value == site_address:
            dns_match = True
            break

    # Also accept if the site address matches the xID owner (site IS the owner)
    record = domain.get("record", {})
    owner_match = record.get("owner", "") == site_address

    if not dns_match and not owner_match:
        log.warning(
            "Site %s claims xid_name '%s' but no DNS record or owner match found "
            "on chain. Claim rejected." % (site_address, xid_name_claim)
        )
        _site_xid_cache[site_address] = {"name": None, "cached_at": now}
        return None

    log.debug(
        "Site %s xid_name '%s' verified (dns=%s, owner=%s)" %
        (site_address, xid_name_claim, dns_match, owner_match)
    )

    entry = {
        "name": name,
        "tld": tld,
        "verified": True,
        "cached_at": now,
    }
    _site_xid_cache[site_address] = entry
    return {"name": name, "tld": tld, "verified": True}


def invalidate_site_xid_cache(site_address=None):
    """Invalidate site xID resolution cache."""
    if site_address:
        _site_xid_cache.pop(site_address, None)
    else:
        _site_xid_cache.clear()


@PluginManager.registerTo("ContentManager")
class ContentManagerPlugin(object):

    def getValidSigners(self, inner_path, content=None):
        """Extend valid signers to resolve xID names in includes signers.

        When an includes entry has xID names (e.g. "smile.epix") in its signers
        array, resolve them to all active linked identity addresses on-chain.
        This allows admins to be referenced by xID in content.json, and key
        rotation is handled automatically via on-chain resolution.
        """
        valid_signers = super(ContentManagerPlugin, self).getValidSigners(inner_path, content)

        resolved = []
        for signer in valid_signers:
            if "." in signer and not signer.startswith("epix1"):
                # Looks like an xID name (e.g. "smile.epix"), resolve it
                parts = signer.rsplit(".", 1)
                if len(parts) == 2:
                    name, tld = parts
                    xid_info = resolve_xid_name(name, tld)
                    if xid_info and xid_info.get("identities"):
                        addrs = [
                            e["address"] for e in xid_info["identities"]
                            if e.get("address") and e.get("active", False)
                        ]
                        if addrs:
                            resolved.extend(addrs)
                            log.debug("Resolved includes signer %s to: %s" % (signer, addrs))
                        else:
                            log.warning("xID signer %s has no active identities" % signer)
                    else:
                        log.warning("Cannot resolve xID signer %s" % signer)
            else:
                resolved.append(signer)

        return resolved

    def resolveUserSigners(self, user_address):
        """For xID-named directories, resolve to all linked identity addresses."""
        if "." not in user_address:
            return super(ContentManagerPlugin, self).resolveUserSigners(user_address)

        parts = user_address.rsplit(".", 1)
        if len(parts) != 2:
            return [user_address]
        name, tld = parts

        xid_info = resolve_xid_name(name, tld)
        if not xid_info or not xid_info.get("identities"):
            log.warning("Cannot resolve xID signers for %s" % user_address)
            return []

        signers = [e["address"] for e in xid_info["identities"] if e.get("address")]
        log.debug("Resolved xID directory %s to signers: %s" % (user_address, signers))
        return signers

    def verifyCert(self, inner_path, content):
        """Override cert verification to handle xID self-signed certs.

        For domain "xid", the cert is self-signed by the user's auth key using
        keccak256. Verification recovers the signer, confirms self-signature,
        then checks on-chain that the xID name has this identity address linked.

        For all other domains, delegates to the standard verifyCert.
        """
        if content.get("cert_user_id") and "@" in content.get("cert_user_id", ""):
            name, domain = content["cert_user_id"].rsplit("@", 1)
            if domain == "xid":
                return self._verifyXidCert(inner_path, content, name)

        return super(ContentManagerPlugin, self).verifyCert(inner_path, content)

    def _verifyXidCert(self, inner_path, content, xid_name):
        """Verify an xID self-signed certificate."""
        from Content.ContentManager import VerifyError
        from Crypt import CryptEpix

        rules = self.getRules(inner_path, content)
        if not rules:
            raise VerifyError("No rules for this file")

        if not rules.get("cert_signers") and not rules.get("cert_signers_pattern"):
            return True

        # Check that "xid" is in cert_signers
        cert_signer_entry = rules.get("cert_signers", {}).get("xid")
        if not cert_signer_entry:
            raise VerifyError("xID cert signer not configured for this site")

        user_address = rules.get("user_address")
        if not user_address:
            raise VerifyError("Cannot determine user address from rules")

        cert_sign = content.get("cert_sign")
        if not cert_sign:
            raise VerifyError("Missing cert_sign for xID cert")

        # If user_address is an xID directory name (contains dot), we can't use
        # it directly as the cert subject. Instead, resolve all linked identity
        # addresses from on-chain data and try each one as the cert subject.
        if "." in user_address:
            tld = "epix"
            name_parts = xid_name.rsplit(".", 1)
            if len(name_parts) == 2:
                xid_name_only, tld = name_parts
            else:
                xid_name_only = xid_name

            xid_info = resolve_xid_name(xid_name_only, tld)
            if not xid_info or not xid_info.get("identities"):
                raise VerifyError("xID name '%s' not found on chain" % xid_name)

            # Try each linked identity as potential signer
            for entry in xid_info["identities"]:
                candidate = entry.get("address")
                if not candidate:
                    continue
                cert_subject = "%s#xid/%s" % (candidate, xid_name)
                recovered = CryptEpix.get_sign_address_keccak(cert_subject, cert_sign)
                if recovered == candidate:
                    user_address = candidate
                    break
            else:
                raise VerifyError("No linked identity matches xID cert signature")
        else:
            # Standard case: user_address is a raw address
            cert_subject = "%s#xid/%s" % (user_address, xid_name)
            recovered_address = CryptEpix.get_sign_address_keccak(cert_subject, cert_sign)
            if not recovered_address:
                raise VerifyError("Could not recover address from xID cert signature")

            if recovered_address != user_address:
                raise VerifyError(
                    "xID cert signature mismatch: recovered %s, expected %s" %
                    (recovered_address, user_address)
                )

        # Step 2: Verify on-chain — xID name must have this identity address linked
        # (For xID directory case, xid_info was already resolved above)
        if not "." in rules.get("user_address", ""):
            tld = "epix"
            name_parts = xid_name.rsplit(".", 1)
            if len(name_parts) == 2:
                xid_name_only, tld = name_parts
            else:
                xid_name_only = xid_name

            xid_info = resolve_xid_name(xid_name_only, tld)
            if not xid_info:
                raise VerifyError("xID name '%s' not found on chain" % xid_name)

        # Find the identity entry for this address (active or revoked)
        identity_entry = None
        for entry in xid_info.get("identities", []):
            if entry.get("address") == user_address:
                identity_entry = entry
                break

        if identity_entry is None:
            raise VerifyError(
                "Identity address %s not linked to xID '%s'" % (user_address, xid_name)
            )

        # Temporal verification: if identity is revoked, only accept content
        # that was modified before the revocation timestamp (plus a grace
        # period to account for clock drift between the user's machine and
        # the chain's block time).
        if not identity_entry["active"]:
            revoked_at_time = identity_entry.get("revoked_at_time", 0)
            content_modified = content.get("modified", 0)
            if revoked_at_time > 0 and content_modified > 0:
                cutoff = revoked_at_time + REVOCATION_GRACE_PERIOD
                if content_modified >= cutoff:
                    raise VerifyError(
                        "Identity %s was revoked at %s but content was modified at %s" %
                        (user_address, revoked_at_time, content_modified)
                    )
                log.debug(
                    "xID cert verified (revoked identity, pre-revocation content): "
                    "%s modified=%s < revoked_at=%s (grace=%ss)" %
                    (user_address, content_modified, revoked_at_time, REVOCATION_GRACE_PERIOD)
                )
            else:
                # No revocation timestamp available — reject to be safe
                raise VerifyError(
                    "Identity address %s has been revoked from xID '%s'" %
                    (user_address, xid_name)
                )
        else:
            log.debug("xID cert verified: %s owns '%s', identity %s linked" %
                       (xid_info["owner"], xid_name, user_address))

        return True

    def sign(self, inner_path="content.json", privatekey=None, filewrite=True,
             update_changed_files=False, extend=None, remove_missing_optional=False):
        """Check identity revocation status before signing user content.

        Old messages from revoked identities remain valid — we only block NEW signing.
        """
        from Content.ContentManager import SignError

        # Only check for user content directories (e.g. data/users/<address>/content.json)
        if "users/" in inner_path:
            match = re.search(r"users/([A-Za-z0-9.]+)/", inner_path)
            if match:
                dir_name = match.group(1)
                if "." in dir_name:
                    # xID directory — check revocation of the actual signing identity
                    # (the cert's auth_address), not the directory name
                    pass  # Revocation is enforced during cert verification
                else:
                    xid_info = resolve_identity_xid(dir_name)
                    if xid_info and not xid_info["active"]:
                        raise SignError(
                            "Your xID identity has been revoked (revoked at block %s). "
                            "You cannot post new content with a revoked identity." % xid_info["revoked_at"]
                        )

        return super(ContentManagerPlugin, self).sign(
            inner_path, privatekey, filewrite,
            update_changed_files, extend, remove_missing_optional
        )


@PluginManager.registerTo("UiWebsocket")
class UiWebsocketPlugin(object):

    def actionXidResolve(self, to, peer_address):
        """Resolve an EpixNet identity address to its xID name.

        If the address matches the current user's site auth_address, also tries
        the user's other known addresses (master + all site auth_addresses).
        Returns {name, tld, owner, active, revoked_at, revoked_at_time} or null.
        """
        # Try the passed-in address first
        result = resolve_identity_xid(peer_address)
        if result:
            self.response(to, result)
            return

        # If the address is the current user's auth for this site, try other addresses
        if hasattr(self, "user") and self.user:
            current_auth = self.user.getAuthAddress(self.site.address, create=False)
            if peer_address == current_auth:
                # Try master_address and all other site auth_addresses
                tried = {peer_address}
                master = getattr(self.user, "master_address", None)
                if master and master not in tried:
                    tried.add(master)
                    result = resolve_identity_xid(master)
                    if result:
                        self.response(to, result)
                        return
                for site_data in self.user.sites.values():
                    auth = site_data.get("auth_address")
                    if auth and auth not in tried:
                        tried.add(auth)
                        result = resolve_identity_xid(auth)
                        if result:
                            self.response(to, result)
                            return

        self.response(to, None)

    def actionXidResolveName(self, to, xid_name):
        """Forward-resolve an xID name (e.g. "peet.epix") to its owner and identities.

        Returns {owner, identities} or null if the name is not registered.
        """
        if not xid_name or not isinstance(xid_name, str):
            return self.response(to, None)

        parts = xid_name.rsplit(".", 1)
        if len(parts) == 2:
            name, tld = parts
        else:
            name, tld = xid_name, "epix"

        result = resolve_xid_name(name, tld)
        self.response(to, result)

    def actionXidResolveBatch(self, to, peer_addresses):
        """Batch resolve multiple identity addresses to xID names.

        Takes a list of addresses (max 50), returns a dict of address -> result.
        """
        if not isinstance(peer_addresses, list):
            return self.response(to, {"error": "peer_addresses must be a list"})

        results = {}
        for addr in peer_addresses[:50]:
            results[addr] = resolve_identity_xid(addr)
        self.response(to, results)

    def actionCertXid(self, to, xid_name=None):
        """Acquire an xID certificate for the current user.

        Creates a self-signed certificate using keccak256 that ties the user's
        auth address to their xID name. The cert is stored locally and used
        when signing content on sites that accept xID certs.

        If xid_name is omitted, tries reverse lookup on all the user's known
        addresses. If none resolve, shows the xID site overlay so the user
        can link their identity.
        """
        if not xid_name:
            # Try reverse lookup on all known addresses
            auth_address = self.user.getAuthAddress(self.site.address)
            tried = set()

            # Try current site auth address
            addresses_to_try = [auth_address]

            # Try master address
            master = getattr(self.user, "master_address", None)
            if master:
                addresses_to_try.append(master)

            # Try all other site auth addresses
            for site_data in self.user.sites.values():
                auth = site_data.get("auth_address")
                if auth:
                    addresses_to_try.append(auth)

            # Invalidate cache for all addresses so we get fresh chain data
            # (user may have just linked their identity on the xID site)
            for addr in addresses_to_try:
                if addr:
                    invalidate_identity_cache(addr)
            invalidate_xid_name_cache()

            for addr in addresses_to_try:
                if addr and addr not in tried:
                    tried.add(addr)
                    result = resolve_identity_xid(addr)
                    if result and result.get("name"):
                        # Found their xID — proceed
                        return self._processCertXid(to, result["name"])

            # No xID found for any address — ask user to open xID site to link identity
            xid_site = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
            return_url = "/%s" % self.site.address
            xid_url = "/%s/?linkIdentity=%s&returnTo=%s" % (
                xid_site, auth_address, return_url
            )

            self.cmd(
                "confirm",
                [
                    "No xID found for your address.<br><br>"
                    "Open the xID site to link <b>%s</b> as an identity?" %
                    (auth_address[:20] + "..."),
                    "Open xID"
                ],
                lambda res: self.cmd("redirect", xid_url)
            )
            return self.response(to, {
                "error": "no_xid_found",
                "auth_address": auth_address
            })

        self._processCertXid(to, xid_name)

    def _processCertXid(self, to, xid_name):
        """Process xID cert acquisition for a given name."""
        from Crypt import CryptEpix

        if not isinstance(xid_name, str):
            return self.response(to, {"error": "Invalid xID name"})

        xid_name = xid_name.strip().lower()
        if not re.match(r'^[a-z0-9][a-z0-9\-]*$', xid_name):
            return self.response(to, {"error": "Invalid xID name format"})

        auth_address = self.user.getAuthAddress(self.site.address)
        auth_privatekey = self.user.getAuthPrivatekey(self.site.address)

        if not auth_address or not auth_privatekey:
            return self.response(to, {"error": "No auth credentials for this site"})

        # Verify on chain: user must own this name and have this identity linked
        tld = "epix"
        invalidate_xid_name_cache("%s.%s" % (xid_name, tld))
        invalidate_identity_cache(auth_address)
        xid_info = resolve_xid_name(xid_name, tld)
        if not xid_info:
            return self.response(to, {
                "error": "xID name '%s' not found on chain" % xid_name
            })

        # Check that identity is actively linked (not revoked)
        identity_linked = any(
            entry.get("address") == auth_address and entry.get("active", False)
            for entry in xid_info.get("identities", [])
        )
        if not identity_linked:
            # Ask user to open xID to link identity
            xid_site = "epix1xauthduuyn63k6kj54jzgp4l8nnjlhrsyaku8c"
            return_url = "/%s" % self.site.address
            xid_url = "/%s/?linkIdentity=%s&returnTo=%s" % (
                xid_site, auth_address, return_url
            )

            self.cmd(
                "confirm",
                [
                    "Your address is not linked as an identity for <b>%s.%s</b>.<br><br>"
                    "Open the xID site to link it?" % (xid_name, tld),
                    "Open xID"
                ],
                lambda res: self.cmd("redirect", xid_url)
            )
            return self.response(to, {
                "error": "identity_not_linked",
                "auth_address": auth_address
            })

        # Create the self-signed cert
        cert_subject = "%s#xid/%s" % (auth_address, xid_name)
        cert_sign = CryptEpix.sign_keccak(cert_subject, auth_privatekey)

        if not cert_sign:
            return self.response(to, {"error": "Failed to sign certificate"})

        # Store the cert
        result = self.user.addCert(auth_address, "xid", "xid", xid_name, cert_sign)

        if result is True:
            self.cmd("notification", [
                "done",
                "xID certificate acquired: <b>%s@xid</b>" % xid_name
            ])
            self.user.setCert(self.site.address, "xid")
            self.site.updateWebsocket(cert_changed="xid")
            self.response(to, "ok")
        elif result is False:
            # Already have a different cert for "xid" domain — replace
            cert_current = self.user.certs["xid"]
            self.cmd(
                "confirm",
                [
                    "You already have an xID cert: <b>%s@xid</b>. Replace?" %
                    cert_current["auth_user_name"],
                    "Replace"
                ],
                lambda res: self._cbCertXidReplace(to, auth_address, xid_name, cert_sign)
            )
        else:
            # Same cert already exists
            self.user.setCert(self.site.address, "xid")
            self.site.updateWebsocket(cert_changed="xid")
            self.response(to, "ok")

    def _cbCertXidReplace(self, to, auth_address, xid_name, cert_sign):
        """Callback to replace an existing xID cert after user confirmation."""
        self.user.deleteCert("xid")
        self.user.addCert(auth_address, "xid", "xid", xid_name, cert_sign)
        self.cmd("notification", [
            "done",
            "xID certificate updated: <b>%s@xid</b>" % xid_name
        ])
        self.user.setCert(self.site.address, "xid")
        self.site.updateWebsocket(cert_changed="xid")
        self.response(to, "ok")

    def actionXidResolveSite(self, to, site_address=None):
        """Resolve a site's canonical xID name from its content.json claim.

        Reads the site's xid_name from content.json, then verifies on-chain
        that the xID DNS record points back to this site address.

        If site_address is omitted, uses the current site.
        Returns {name, tld, verified} or null if no valid claim.
        """
        import main as main_module

        if site_address:
            site = main_module.file_server.sites.get(site_address)
            if not site:
                return self.response(to, {"error": "Site not found"})
        else:
            site = self.site

        result = resolve_site_xid(site)
        self.response(to, result)

    def actionXidInvalidateCache(self, to, peer_address=None):
        """Invalidate the xID identity, name, and site caches."""
        invalidate_identity_cache(peer_address)
        invalidate_xid_name_cache()
        invalidate_site_xid_cache()
        self.response(to, "ok")


@PluginManager.registerTo("ConfigPlugin")
class ConfigPlugin(object):
    def createArguments(self):
        group = self.parser.add_argument_group("xID Resolver plugin")
        group.add_argument(
            '--xid-rpc-url',
            help='Epix Chain REST API URL for xID identity resolution',
            default='https://api.testnet.epix.zone',
            metavar='url'
        )
        return super(ConfigPlugin, self).createArguments()
