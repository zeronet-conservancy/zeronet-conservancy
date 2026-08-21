Name:           zeronet-conservancy
Version:        1.0.18
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
* Fri Aug 21 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.18-1
- Add: a real "ZeroTalk (local identity)" starter template in the New
  Site page, alongside 1.0.17's ZeroMail one -- a working fork of
  ZeroTalk wired to the local identity provider instead of
  zeroid.bit/kxoid.bit, using the same contentSign-based publish path.
  Needed one less fix than ZeroMail: ZeroTalk's own bundled ZeroFrame
  already sent wrapper_nonce correctly.
* Fri Aug 21 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.17-1
- Add: a self-hosted local identity provider, now actually surfaced in
  the UI (certSelect popup + Sidebar panel) -- issue and select your
  own certificates without registering with zeroid.bit.
- Add: ContentManager.signUserContent(), the missing write path for
  non-root (multi-user "user_contents") content.json -- lets a site
  contributor without ADMIN actually publish, via a new contentSign
  command and a scoped fileWrite relaxation.
- Add: a real "ZeroMail (local identity)" starter template in the New
  Site page, a working fork of ZeroMail wired to the new local
  identity provider instead of zeroid.bit.
- Add: User.local_names -- a local, per-user address-to-name override,
  independent of any site's self-claimed username -- with management
  UI on the renamed "User management" dashboard page (was "Content
  filters").
- Fix: several bugs found only by actually driving the new ZeroMail
  fork live -- a missing wrapper_nonce broke every postMessage from a
  site, a missing data/archived.json crashed the contacts list, the
  CryptMessage plugin's own param parsing silently dropped every
  real (positional) site call, a one-shot Promise meant a fresh
  mailbox registration never appeared without a manual reload, and
  the site's cert identity could be silently wiped by an unrelated
  broadcast right after publishing.
* Thu Aug 20 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.16-1
- Add: MuteList (dashboard's Mute/Block panel), uiLogout (dashboard's
  Logout button), OptionalHelp/OptionalHelpList/OptionalHelpRemove/
  OptionalHelpAll ("help seed this directory"), announcerStats
  (all-sites tracker aggregation), feedSearch (cross-site feed
  full-text search), filterIncludeAdd/filterIncludeRemove (subscribe
  to another site's block/mute list), and chartDbQuery (a real,
  queryable chart.db for the dashboard's Charts page). All found
  missing auditing every bundled site's own websocket calls against
  this stack's registered commands.
* Thu Aug 20 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.15-1
- Add: fileRules websocket command (a real port of the original
  actionFileRules) -- fixes the Sidebar plugin's own Sign/Publish menu
  (content.json chooser dropdown), which silently couldn't determine
  whether the connected identity could sign directly, and ZeroMail's
  quota display.
* Thu Aug 20 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.14-1
- Fix: config.user_agent ("conservancy", 11 chars) was too long for
  ZeroMail's own fixed-width status-line padding (hardcoded to a
  budget of 18 chars), causing a RangeError that crashed ZeroMail's
  initial render and made "New message" (and other actions) silently
  do nothing. Reverted to "zeronet" (7 chars), the value this budget
  was actually tuned for -- fixes ZeroMail and any other site making
  the same fixed-width assumption.
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
