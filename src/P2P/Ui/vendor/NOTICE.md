# Vendored: Pico CSS

- File: `pico.min.css`
- Version: 2.1.1
- Source: https://picocss.com (https://github.com/picocss/pico)
- License: MIT (Copyright (c) 2019-2024 Pico)

Vendored (not CDN-linked) because this app is offline-first -- the native
dashboard pages (`P2P/Ui/templates/`) must render with zero network
dependency. Inlined directly into each rendered page's `<style>` via
`Dashboard.py`, not served from a separate URL, so a page load never
depends on `/uimedia` or any other route either.

To update: replace this file with a newer `pico.min.css` build from
https://picocss.com/docs/version-picker and bump the version noted above.
