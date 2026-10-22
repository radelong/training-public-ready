# Class slide viewer update

This offline update presents one PDF slide at a time inside each course module. It provides previous/next controls, page entry, keyboard navigation, full-screen viewing, and a separate link to the original PDF. PDF.js 5.6.205 and its required assets are bundled, so rendering does not depend on a CDN or internet access.

## Package use

1. Verify the archive: `sha256sum -c Academy_Class_Slide_Viewer_20261022.tar.gz.sha256`.
2. Extract it to a temporary directory.
3. From that directory, verify `sha256sum -c SHA256SUMS.txt`.
4. Review `README.md` and run `sudo bash scripts/install-class-slide-viewer.sh` only when the supported source-version checks pass.
5. Do not bypass a version mismatch. The installer backs up replaced files and restores them if installation fails.

This is an incremental update, not a complete installation image.
