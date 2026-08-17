Name:           zeronet-conservancy
Version:        1.0.1
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
* Mon Aug 17 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.1-1
- Fix broken Windows MSI and Linux AppImage/deb desktop packages
  (pywebview2 0.1.4)
* Sun Aug 16 2026 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 1.0.0-1
- trio/libp2p-native rewrite; legacy gevent stack removed
* Thu Jan 01 1970 ZeroNet Conservancy <maintainers@zeronetconservancy.org> - 0.7.10-1
- Initial desktop package
