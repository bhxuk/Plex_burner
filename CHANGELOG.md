# Changelog

All notable changes to Plex Burner are listed here. The website shows this file, and the in-app
updater checks `app/VERSION`, so every release needs an entry. Versions follow [semantic versioning](https://semver.org).

## [1.3.2] - 2026-11-01

### Added
- **Rename** anything in the Library: open it and press Rename. The folder and the video files inside are renamed together, so your media server picks up the new name

### Fixed
- Old bookmarks to `/dashboard` open the app instead of a Not Found page

## [1.3.1] - 2026-11-01

### Fixed
- A newly inserted disc is picked up within a few seconds. The drive is now asked whether a disc is ready instead of being test-read, which failed while a disc was still spinning up
- The Disc tab says when the tray is open or a disc is still loading

## [1.3.0] - 2026-11-01

A full rebuild: a proper dashboard, playable video files and support for several drives.

### Added
- **Several drives at once:** every DVD drive is found automatically, including USB drives plugged in later, and each one copies in parallel with its own card on the Disc tab
- **Video files instead of disc images:** films are saved as MKV at original quality with every audio track and subtitle, or as MP4 converted to H.264 so they play on anything. A full disc backup is still available. Choose in **Settings**
- **Home video discs:** discs from DVD recorders and camcorders are read and their videos converted to MKV or MP4. Discs without video are saved as a folder of their files
- **Previews:** frames read from the disc before you copy it, a live picture while it copies, and preview frames for everything in your library
- **Disc details:** running time, chapters, number of titles, picture format, audio languages and subtitles
- **Library tab:** everything in your save locations with frames, search and filters
- **Locations tab:** save to several folders, see free space and how many more DVDs fit, browse and create folders, pick a default
- **Cancel** a copy, and see what it is doing, how fast and how long is left
- Typing a name or picking a folder restarts the auto-start timer and is used when it fires
- Public website with a live demo

### Changed
- Updates now pull the new version from GitHub and restart the app, like other self-hosted apps. The Docker socket is no longer needed
- Settings moved to `.env` and the app's **Settings** tab, so updates never touch them
- Each copy goes in its own folder named after the film, the layout Plex, Jellyfin and Emby expect

### Removed
- ISO disc images for data discs. Their contents are saved as playable files instead
- The changelog inside the app. It is on the website

## [1.2.0] - 2026-11-01

### Added
- Choose where discs are saved: browse folders on the server, create new folders, and see free space before you copy
- Copied files are owned by your server user instead of root

## [1.1.0] - 2026-11-01

### Added
- Project website and README

### Fixed
- The app no longer gets stuck after a disc is ejected

## [1.0.0] - 2026-11-01

### Added
- First release: detect a disc, suggest a name, copy it to a media folder and eject it, with a dashboard and one-click updates
