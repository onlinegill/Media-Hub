# Media Hub for Home Assistant

**Media Hub** is a standalone Home Assistant App for local audio, speaker control,
internet radio, private media uploads, and scheduled playback.

Designed by **Sukhpal Gill**.

## Why I built Media Hub

I was asked by a school to set up a smart school bell that would ring over Sonos
speakers every 45 minutes when the period changed. While building that system, I
realized that managing audio files, speaker groups, radio streams, and large
recurring timetables could be much easier from one dashboard.

That is why I built **Media Hub**.

## Features

- Browse Home Assistant's existing media library.
- Private Media Hub audio library with browser uploads.
- Multi-file audio upload and file deletion.
- 20 media items per page with Previous/Next controls and scrolling.
- Automatic Home Assistant speaker and media-player group discovery.
- Sonos-friendly speaker/group playback workflows.
- Save a default output and identify it with a star.
- Play, pause, stop, volume, and optional announcement controls.
- Now Playing information and artwork when available.
- Play buttons switch to Stop while playback is active.
- Add, test, edit, play, and delete custom internet radio stations.
- Follow redirects and common M3U/PLS playlists.
- Audio MIME detection and tokenized LAN stream proxy for network speakers.
- Verify real playback state before reporting a radio stream as playing.
- Weekly recurring playback schedules.
- One-time calendar-date schedules.
- Bulk-add many times to multiple weekdays.
- Different times can be maintained for each weekday.
- Flexible time entry: `09:05`, `0905`, `9:05`, `905`, `17:58`, `1758`.
- Choose the media file, output, volume, and announcement mode for each schedule.
- Enable/disable, edit, delete, and Run Now schedule controls.
- Uses the Home Assistant configured time zone.
- Runs continuously as a Home Assistant App.
- Automatic startup with Home Assistant.
- Home Assistant Ingress and sidebar access.
- Responsive desktop/mobile UI with light/dark support.
- Persistent settings, radio stations, schedules, and uploaded audio.

## Install

In Home Assistant:

**Settings → Apps → App Store → ⋮ → Repositories**

Add the URL of this GitHub repository, refresh the App Store, and install
**Media Hub**.

Start the App once. It is configured to start automatically on future Home
Assistant boots.

## Network requirement

Network speakers fetch media from Media Hub on **TCP port 8100**. The Home
Assistant host must be reachable from the speaker network on that port.

## Persistent storage

Media Hub configuration:

```text
/data/media_hub.json
```

Private uploaded media:

```text
/data/library/
```

Existing Home Assistant media is read from the standard read-only media mount.

## Privacy

This public repository contains no preconfigured radio stations, speaker entity
IDs, device IDs, timetable entries, uploaded audio, or user schedules. Those are
created and stored locally by each Media Hub installation.

## Version

**1.0.0 — Initial public release**
