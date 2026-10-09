# Changelog

## Unreleased

### Fixed
- Bell playback resilience (v1.2.3): when Home Assistant answers HTTP 500
  "Timeout while waiting for Sonos player to join the group", the bell now
  retries once after 5s instead of failing. The v1.2.2 retry only covered
  client-side `play_media` timeouts; the group-join timeout surfaces as an HA
  500 error and needed its own retry (seen 2026-10-09 at BBY).

### Fixed
- Bell playback resilience: `play_media` now gets a 30s timeout (up from 10s)
  and one automatic retry when Sonos speakers are slow to acknowledge, so a
  sluggish speaker no longer swallows a scheduled bell (TimeoutError seen
  2026-10-08 at BBY).

### Added
- Scheduler time zone override: set `time_zone` in the add-on configuration
  (e.g. `America/Chicago`), or edit it live in Media Hub Settings. Priority is
  Settings UI, then the add-on option, then the Home Assistant time zone,
  then UTC. Fixes schedules firing in UTC when HA time zone auto-detection
  fails at startup.

### Added
- Playlist shuffle option: randomize the song order each time a playlist starts.
  The toggle sits next to "Repeat until stopped" in the playlist editor, and the
  saved song order is preserved for editing.

### Fixed
- Playlist Play and scheduled starts now use the validated playlist, so a stored
  playlist with missing or invalid songs is rejected cleanly instead of failing
  mid-start.

## 1.1.2

### Fixed
- Restore App startup after 1.1.1. The startup log used an invalid `bashio`
  version expression, which stopped the container from launching. The log message
  no longer references the version; the running version is still logged by the App.

## 1.1.1

### Fixed
- Never cache the dashboard page and playlist script, so a new tab (such as Playlists) appears immediately after updating instead of a stale cached interface.
- Report the real App version in the startup log instead of a hardcoded older version.
- Send the running App version in outbound HTTP User-Agent headers.

## 1.1.0

### Added
- Saved playlists with ordered songs from Home Assistant media and private uploads.
- Automatic next-song playback, repeat, pause/resume, stop, and next-song controls.
- Weekly and one-time playlist schedules with output, volume, and optional same-day stop time.
- Playlist progress in Now Playing; playback continues with the dashboard closed.

### Fixed
- Resolve grouped speaker controls to their coordinator.
- Preserve disabled schedules when editing and allow a scheduled volume of zero.

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
