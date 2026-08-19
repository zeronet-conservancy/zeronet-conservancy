Name:           zeronet-conservancy
Version:        1.0.13
Release:        1%{?dist}
Summary:        ZeroNet Conservancy desktop application
License:        GPL-3.0-or-later
BuildArch:      x86_64

%description
ZeroNet Conservancy packaged desktop application.

%install
rm -rf %{buildroot}
install -d %{buildroot}/opt/zeronet-conservancy
cp -a %{_source_dir}/. %{buildroot}/opt/zeronet-conservancy/
install -d %{buildroot}/usr/bin
ln -s /opt/zeronet-conservancy/ZeroNet %{buildroot}/usr/bin/zeronet-conservancy

%files
/opt/zeronet-conservancy
/usr/bin/zeronet-conservancy

%changelog
* Thu Aug 20 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.13-1
- Overhaul the Configuration/Plugins/New site/Content filters/Files/
  Console admin pages: shared layout, vendored offline-first Pico CSS,
  real dark/light theme application (previously the drawer's theme
  switcher never actually changed the page). Fixes page titles that
  silently rendered blank on every one of these pages.
* Wed Aug 19 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.12-1
- Add private-site access-request management: owner UI (recipients list,
  pending-requests list with one-click approve/deny), direct P2P push
  for siteRequestAccess instead of manual out-of-band relay, and a
  bounded/TTL'd bystander store-and-forward relay so a request still
  reaches an owner who's offline at request time.
- Fix: new sites never got ADMIN on themselves after creation
  (siteCreate, siteBuilderCreate, siteClone, and the CLI siteCreate
  action all only persisted SiteManager's own "own" setting, never
  granted the Site object ADMIN) -- a freshly created site's sidebar
  owner controls didn't render until a restart round-tripped
  permissions through sites.json. Also fixes the left-drawer's "New
  site" button silently doing nothing on error.
* Wed Aug 19 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.11-1
- Add private-site support: per-recipient AES-encrypted site content
  with ECIES-wrapped keys, re-ported from the pre-libp2p-migration
  design. siteRequestAccess/siteAddRecipient/siteRemoveRecipient
  websocket commands; fileGet/fileWrite and the site's raw HTTP media
  path transparently encrypt/decrypt for approved recipients. No
  browser dashboard UI for approval/revocation yet -- goes through
  those commands directly for now.
* Tue Aug 18 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.10-1
- Fix two real gaps in P2P announce/discovery wiring: sites added to an
  already-running node now get their announce loop started immediately
  (previously only sites present at startup were ever periodically
  re-announced), and a new --dht-bootstrap flag lets a fresh node seed
  its DHT routing table with known peers (previously no bootstrap
  mechanism existed at all, so DHT discovery could never find a first
  peer on a cold start)
- Fix the packaged desktop app missing the Newsfeed plugin's Db
  dependency (legacy src/Db/ package, only reached via dynamic plugin
  loading so PyInstaller's static analysis never bundled it) --
  "Plugin Newsfeed load error: No module named 'Db'" at startup
* Tue Aug 18 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.9-1
- Add gossipsub-based content.json propagation alongside the existing
  unicast push: sites now gossip updates to their mesh of subscribed
  peers (GossipManager, one topic per site), reusing the same
  signature-verification path as the unicast RPC so both transports
  apply identical validation before writing anything
* Tue Aug 18 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.8-1
- Fix the Sidebar plugin's own JS/CSS (drag-to-open gesture, Console
  panel, left-edge nav drawer) missing from every packaged desktop and
  Android build since 1.0.0 -- plugins/Sidebar/media was dropped from
  the PyInstaller resources list by a pre-1.0.0 cleanup that mistook it
  for dead legacy code
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.7-1
- Add a persistent left-edge nav drawer (New site, Content filters,
  Configuration, Plugins, Theme, Language, Update all sites, Show data
  directory, Shut down), present on every page including /Config and
  /Plugins, not just site pages; fix language/theme settings silently
  not taking effect after being changed (both were hardcoded in the
  wrapper's own render regardless of the saved preference)
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.6-1
- Fix /uimedia/all.js|all.css never cache-busting across versions (the
  wrapper page's ?rev= was hardcoded to "", so upgrades kept serving a
  previously-cached bundle forever) and right-click doing nothing in
  the packaged desktop app on any platform (pywebview2 tied the whole
  context menu, not just devtools, to its debug flag; fixed in the
  pywebview2 fork with a setting that decouples the two)
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.5-1
- Add a /SiteBuilder dashboard page (a "New site" flow with starter
  templates) and a /ContentFilter dashboard page (view/remove blocked
  sites and muted users) -- both plugins already worked over the
  websocket API but had no UI anywhere to reach them
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.4-1
- Fix the sidebar drag-to-open gesture not working under WebKitGTK
  (the packaged desktop app's webview engine): WebKitGTK coalesces an
  entire drag into a single mousemove event, which the previous code
  needed at least two of to do anything. Calibrate the grab offset
  from mousedown and replay the drag against the first mousemove
  instead of waiting for a second one that may never arrive
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.3-1
- Silence a spurious gevent MonkeyPatchWarning on startup (harmless
  side effect of importing trio/libp2p before gevent patches ssl);
  bumped pywebview2 to 0.1.6 (GTK drag-region compatibility fix,
  not used by this app)
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.2-1
- Fix Android crashes: drop the unnecessary Kivy requirement from the
  generated Buildozer project and harden WebView teardown/pause-resume
  (pywebview2 0.1.5)
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.1-1
- Fix broken Windows MSI and Linux AppImage/deb desktop packages
  (pywebview2 0.1.4)
* Sun Aug 16 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.0-1
- trio/libp2p-native rewrite; legacy gevent stack removed
* Thu Jan 01 1970 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 0.7.10-1
- Initial desktop package
