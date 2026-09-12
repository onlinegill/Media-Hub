# Changelog

## 1.0.1

### Fixed
- Fixed issue where Now Playing displayed "Nothing playing" during active playback on speaker groups (such as "All Sonos") and media players without direct title attributes.
- Inherited metadata and artwork from active group coordinator and member speakers.
- Added active local playback session tracking so selected audio titles always show during playback.

## 1.0.0

Initial public release.

### Included

- Home Assistant local-media browser
- Private persistent Media Hub upload library
- 20-item media pagination and scrollable library view
- Speaker and group discovery
- Default output with star indicator
- Play, pause, stop, volume, and announcement controls
- Now Playing status and artwork
- Dynamic Play/Stop controls
- Custom radio station manager
- Radio stream testing, redirect handling, playlist resolving, and MIME detection
- Direct and proxied radio playback
- Playback verification against the effective media player
- Weekly scheduled playback
- One-time calendar-date playback
- Bulk schedule time entry across selected weekdays
- Flexible time formats such as `09:05`, `0905`, `9:05`, and `905`
- Schedule enable/disable, edit, delete, and Run Now
- Home Assistant time-zone support
- Home Assistant Ingress sidebar interface
- Automatic App startup
- Persistent App configuration and uploaded media
- Responsive light/dark dashboard
