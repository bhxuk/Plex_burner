# Changelog

## 1.2.0
- Choose where discs are saved: browse folders on the server, create new folders, and see free space before you copy.
- The chosen folder is remembered across restarts and updates.
- Copied files are owned by your server user instead of root.
- Network shares mounted under /mnt show up without restarting the app.

## 1.1.0
- Added a project website on GitHub Pages with install steps, a dashboard preview and a link to open your own dashboard.
- Added a README.
- A disc now only counts as present when it can be read, so the app no longer gets stuck after an eject.

## 1.0.0
- First release: copy DVDs to a Plex-ready folder (VIDEO_TS) and data discs to ISO.
- Detects the disc, suggests a name from the disc title, and lets you change it.
- Auto-starts after a set delay if nobody names the disc.
- Ejects the disc when the copy finishes.
- Dashboard on port 9000 with a one-click update button and this changelog.
