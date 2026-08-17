Name:           zeronet-conservancy
Version:        1.0.5
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
