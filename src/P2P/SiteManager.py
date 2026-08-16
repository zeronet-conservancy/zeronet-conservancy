"""Trio port of Site/SiteManager.py -- scoped to what this stack's Site
model actually supports: loading/saving the flat address->settings map in
private/sites.json, add()/get()/need()/delete(), and address validation.

NOT ported:
  - ContentDb-based orphan-row cleanup in load() -- ContentDb.py isn't
    part of this stack (P2P.ContentManager keeps a plain in-memory dict,
    see its own module docstring).
  - site.settings as an attribute ON Site itself. P2P.Site.py already has
    an established, tested attribute-based model (self.serving,
    self.permissions, self.wrapper_key/ajax_key) that Wrapper.py and
    P2P/Ui/commands.py already depend on -- bolting a parallel
    self.settings dict onto Site.py for SiteManager's sake would create
    two sources of truth for "serving" inside one object. Instead the
    settings SiteManager actually needs to persist (serving/own/added/
    size/size_optional) live here, in SiteManager, keyed by address
    alongside each Site -- read at load(), written at save().
  - site.download() on add() -- kicking off a real peer-fetch download
    needs WorkerManager wired to a specific site's connectable peers, a
    separate piece of work; add() here just creates the Site and lets the
    caller (or a later download-orchestration pass) decide what happens
    next.

Phase 8: @acceptPlugins marks this class as pluggable, and isDomain()/
resolveDomain() are async now (the core stubs are trivial, but a real
resolver -- e.g. a P2P/plugins/Zeroname port reading a resolver site's
data/names.json -- needs to do real file I/O, and every I/O-touching
method in this stack is async by convention). get()/need() now actually
call them before falling back to a plain address lookup, matching the
original's own get()/need() -- previously these two stubs existed but
nothing in this file consulted them, so even a plugin overriding them
would have had no effect.
"""
import json
import logging
import re
import time

import trio

from .PluginManager import acceptPlugins
from .Site import Site

ADDRESS_RE = re.compile(r"^[A-Za-z0-9]{26,35}$")


@acceptPlugins
class SiteManager:
    def __init__(self, data_dir, private_dir=None):
        self.data_dir = data_dir
        self.private_dir = private_dir if private_dir is not None else data_dir
        self.log = logging.getLogger("P2P.SiteManager")
        self.sites: dict[str, Site] = {}
        self._site_settings: dict[str, dict] = {}  # address -> {serving, own, added, size, size_optional}
        self.loaded = False

    def isAddress(self, address: str) -> bool:
        return bool(ADDRESS_RE.match(address))

    async def isDomain(self, address: str) -> bool:
        return False  # No built-in domain resolution -- see module docstring

    async def resolveDomain(self, domain: str):
        return False

    def _sitesJsonPath(self):
        return self.private_dir / "sites.json"

    async def load(self, cleanup: bool = True) -> None:
        """(Re)reads private_dir/sites.json: creates a Site for every
        address not already loaded, and (if cleanup) drops any currently
        loaded site whose address is no longer listed.

        Also loads each new Site's own on-disk content.json into its
        ContentManager, if present -- found live, driving the real
        ZeroHello dashboard against an already-downloaded site: nothing
        anywhere calls ContentManager.loadContent() for a site that
        already exists on disk at boot (only a fresh download, a
        siteSign, or a CLI action ever did), so formatSiteInfo()'s
        `content` stayed None and `size` stayed 0 forever for every site
        the server already had -- not just briefly until some lazy
        trigger, since nothing was ever going to trigger it. That crashed
        the real wrapper.js in multiple places that assume a loaded
        site's `content` is either a real object or genuinely still-
        downloading, never "loaded but nobody told ContentManager".
        Best-effort and silent on failure (corrupt/missing content.json
        is exactly the "not downloaded yet" case _tryDownloadSite/
        UiServer already handle via the same isFile() check)."""
        try:
            raw = await trio.to_thread.run_sync(self._sitesJsonPath().read_text)
            data = json.loads(raw)
        except FileNotFoundError:
            data = {}

        address_found = set()
        for address, settings in data.items():
            address_found.add(address)
            if address in self.sites:
                continue
            if not self.isAddress(address):
                self.log.warning("Skipping invalid address in sites.json: %s", address)
                continue
            site_root = self.data_dir / address
            site = Site(
                address, site_root, serving=bool(settings.get("serving", True)),
                permissions=settings.get("permissions"),
            )
            if site.storage.isFile("content.json"):
                try:
                    await site.content_manager.loadContent()
                except Exception:
                    self.log.exception("Failed to load content.json for %s", address)
            self.sites[address] = site
            self._site_settings[address] = dict(settings)

        if cleanup:
            for address in list(self.sites):
                if address not in address_found:
                    del self.sites[address]
                    self._site_settings.pop(address, None)
                    self.log.debug("Removed site: %s", address)

        self.loaded = True

    async def save(self) -> None:
        """Writes every currently loaded site's settings back to
        sites.json, refreshing "serving", "size"/"size_optional", and
        "permissions" from the live Site/ContentManager first -- a granted
        ADMIN permission (or any other) needs to survive a process
        restart the same way the original's Site.saveSettings() does, not
        just live in the in-memory Site object for the rest of this run."""
        data = {}
        for address, site in self.sites.items():
            settings = self._site_settings.setdefault(address, {"added": int(time.time()), "own": False})
            settings["serving"] = site.isServing()
            settings["size"] = site.content_manager.getTotalSize()
            settings["permissions"] = list(site.permissions)
            data[address] = settings

        body = json.dumps(data, indent=1, sort_keys=True)
        await trio.to_thread.run_sync(self._sitesJsonPath().write_text, body)

    async def get(self, address: str):
        if await self.isDomain(address):
            resolved = await self.resolveDomain(address)
            if resolved:
                address = resolved
        return self.sites.get(address)

    def isOwn(self, address: str) -> bool:
        return bool(self._site_settings.get(address, {}).get("own", False))

    async def setOwn(self, address: str, own: bool) -> None:
        self._site_settings.setdefault(address, {"added": int(time.time())})["own"] = own
        await self.save()

    def getSizeLimitOverride(self, address: str) -> float | None:
        """An admin-set override of content.json's own declared size_limit
        (the sidebar's "Set" button) -- kept here rather than on Site
        itself, same "flat address->settings map" precedent as own/
        permissions above; formatSiteInfo() prefers this when present."""
        return self._site_settings.get(address, {}).get("size_limit_override")

    async def setSizeLimitOverride(self, address: str, size_limit: float) -> None:
        self._site_settings.setdefault(address, {"added": int(time.time())})["size_limit_override"] = size_limit
        await self.save()

    def add(self, address: str, own: bool = False):
        """Returns the new (or already-existing) Site, or False if address
        isn't a valid site address."""
        if address in self.sites:
            return self.sites[address]
        if not self.isAddress(address):
            return False

        site_root = self.data_dir / address
        site = Site(address, site_root, serving=True)
        self.sites[address] = site
        self._site_settings[address] = {"added": int(time.time()), "own": own, "serving": True}
        self.log.debug("Added new site: %s", address)
        return site

    async def need(self, address: str, **kwargs):
        if await self.isDomain(address):
            resolved = await self.resolveDomain(address)
            if resolved:
                address = resolved
        site = self.sites.get(address)
        if not site:
            site = self.add(address, **kwargs)
        return site

    def delete(self, address: str) -> None:
        self.sites.pop(address, None)
        self._site_settings.pop(address, None)
        self.log.debug("Deleted site: %s", address)

    def list(self) -> dict:
        return self.sites
