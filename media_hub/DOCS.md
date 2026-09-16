# Media Hub

Media Hub is a universal media player and audio manager for Home Assistant for controlling playback, speaker outputs, multi-room groups, internet radio streams, uploaded audio files, and scheduled playback from one unified interface.

## Why Media Hub exists

I was asked by a school to set up a school bell, so I built this smart school
bell that would ring over Sonos speakers every 45 minutes when the period
changed. Building that system made me realize how useful it would be to have
one simple Home Assistant media dashboard for local audio, speaker groups, radio
streams, uploads, and recurring schedules.

What began as an automated bell system evolved into a complete **Universal Media Player** for Home Assistant.

## Features

### Home Assistant media library

- Browse audio already stored in Home Assistant's existing Media folder.
- Navigate folders without creating a second copy of the files.
- Search the current folder.
- Display audio type and file size.
- Show 20 items per page.
- Previous/Next page controls.
- Scrollable media list for compact dashboards.

### Private Media Hub library

- Upload audio directly from the Media Hub dashboard.
- Upload multiple files.
- Supported library formats include MP3, M4A, AAC, FLAC, WAV, OGG, OGA, and
  Opus.
- Uploaded files are stored persistently inside the App.
- Delete uploaded files from the dashboard.
- Uploaded audio remains available after App restarts and App upgrades.

### Speaker and group control

- Automatically discovers speaker-style `media_player` entities from Home
  Assistant.
- Works with individual speakers and media-player groups.
- Supports Sonos speaker/group workflows.
- Select any discovered output.
- Save a default output.
- The default output is marked with a star.
- Play, pause, stop, and volume controls.
- Now Playing status and available artwork.
- The Play control changes to Stop while the selected output is playing.
- Optional announcement mode for supported players.

### Internet radio

- Add your own station name and HTTP/HTTPS stream URL.
- Edit and delete saved stations.
- Test a stream before saving it.
- Follows common redirects.
- Resolves common M3U and PLS playlists.
- Detects common audio MIME types.
- Uses direct playback when appropriate.
- Includes a tokenized LAN radio proxy for streams that need a speaker-friendly
  MIME type.
- Verifies that the effective speaker actually enters the Playing state before
  reporting success.
- Can resolve compatible media-player helper/group entities to a real playback
  coordinator.
- A radio Play button changes to Stop while that station is active.

Media Hub does not include any preconfigured radio stations. Stations are stored
only in your own local App data.

### Scheduled playback

Media Hub includes its own scheduling page, so large recurring audio timetables
can be managed without manually editing Home Assistant automation YAML.

Schedules can use:

- Any audio file from the Home Assistant media library.
- Any audio file from the private Media Hub library.
- Any discovered speaker or speaker group.
- Optional playback volume.
- Optional announcement mode.
- Enable/disable controls.
- Edit and delete controls.
- **Run now** for testing.

#### Recurring weekly schedules

- Enter different times for each weekday.
- Paste many times at once.
- Select several days and apply one bulk list to all selected days.
- Edit individual days afterward.
- Useful for school bells, shift changes, recurring announcements, prayer times,
  break reminders, opening/closing audio, and similar recurring audio workflows.

#### One-time schedules

- Choose a calendar date.
- Enter one or several playback times for that date.

#### Flexible time entry

The scheduler accepts standard or compact 24-hour time:

- `09:05`
- `9:05`
- `0905`
- `905`
- `17:58`
- `1758`

All valid entries are normalized to `HH:MM`.

### Lunch and recess playlists

1. Open **Playlists → New playlist**, enter a name such as **Lunch**, and add songs
   from Home Assistant media or the Media Hub Library. Upload audio on the Player
   tab first if necessary.
2. Use the up/down buttons to arrange songs. Enable **Repeat until stopped** if
   the music should loop until the end of the break, then save.
3. Open **Schedules → New schedule**. Choose the playlist under Media, select
   the speaker/group, and set the volume.
4. Enter the lunch start time for the school weekdays and an optional **Stop time**.
   For example, Monday–Friday at **12:00**, stopping at **12:30**. Stop times use
   the Home Assistant time zone and must follow every start time on the same day.
5. Create a separate **Recess** schedule with its own start and stop times. Use
   **Run now** before that day's stop time to test, or **Play** on a playlist to
   test without a timed stop. Manual Play uses the output selected on the Player tab.

Songs advance automatically, and the dashboard can be closed. Now Playing shows
the playlist and song number. Pause/resume, Stop, and Next control the active queue.
A playlist without repeat finishes after its last song. With repeat enabled and
no stop time, it continues until stopped.

Use **Stop in Media Hub** to cancel the queue. Starting another file, radio station,
or playlist on that output cancels the previous queue, including its stop timer.
Scheduled announcements also replace a queue; it does not resume after the bell.
Editing a playlist affects its next run. Schedules reference the saved playlist,
so remove or change those schedules before deleting it.

Automatic advancement requires the speaker integration to report **playing** and
then **idle** at the end of a song; pauses and buffering do not advance the queue.
There may be a short gap between songs. A stop issued outside Media Hub can look
like a finished song and advance the queue; use Media Hub's Stop button instead.
If playback cannot be confirmed within 60 seconds, a song is missing, or the speaker
becomes unavailable, the queue ends and errors are recorded in the app log.
Known changes to the playing media outside Media Hub relinquish queue control.
Test playback and transitions on the actual speaker/group before unattended use.

Saved playlists and schedules survive app restarts; active queues and stop timers
do not. Restarting the app during playback stops advancement but may leave the
current song playing on the speaker. Stop it manually if needed. Start times missed
while the app is offline are not replayed. Weekly schedules run on every selected
weekday, including school holidays, unless disabled.

### Time zone handling

Schedules use the time zone configured in Home Assistant. The detected time zone
is shown inside Media Hub settings and on the Schedules page.

### Home Assistant integration

- Runs as a normal Home Assistant App.
- Starts automatically with Home Assistant.
- Uses Home Assistant Ingress.
- Opens directly from the Home Assistant sidebar.
- Uses the Home Assistant API for media-player state and services.
- Does not require a separate custom integration.
- Does not require users to manually maintain Media Hub automation YAML.

### Responsive dashboard

- Desktop and mobile-friendly interface.
- Light and dark mode support through browser color preference.
- Compact header.
- Connection status.
- App version display.
- Built-in Media Hub icon rendered inline in the dashboard to avoid Ingress
  image-path issues.
- UI credit: **Designed by Sukhpal Gill**.

## Installation

1. Create or open the public GitHub repository containing these files.
2. In Home Assistant, open:
   **Settings → Apps → App Store → ⋮ → Repositories**
3. Add the GitHub repository URL.
4. Refresh the App Store.
5. Install **Media Hub**.
6. Start **Media Hub**.
7. Open **Media Hub** from the Home Assistant sidebar.

The App is configured to start automatically on future Home Assistant boots.

## Network media port

Media Hub exposes **TCP port 8100** for tokenized media URLs that network speakers
need to fetch.

The dashboard itself remains behind Home Assistant Ingress. The LAN port is used
only for media/stream delivery.

For playback to work, speakers must be able to reach the Home Assistant host on
TCP port 8100.

## Persistent data

Media Hub stores its persistent configuration inside the App data directory.

Main data file:

```text
/data/media_hub.json
```

This stores:

- Saved radio stations
- Default output
- Media Hub settings
- Schedules
- Scheduler run tracking
- Internal media-access token

Private uploaded media is stored under:

```text
/data/library/
```

Home Assistant's existing media is mounted read-only at:

```text
/media/
```

Normally these paths do not need to be edited manually; the Media Hub dashboard
manages them.

## Privacy

The public Media Hub package contains no user-specific:

- Radio station names or URLs
- Speaker entity IDs
- Device IDs
- School bell times
- Automation IDs
- Uploaded media
- Saved schedules

Those items are created locally by each user and remain in that user's Home
Assistant App data.

## Supported architecture

The App repository currently declares support for:

- `amd64`
- `aarch64`

## Notes

Media compatibility ultimately depends on the capabilities of the selected Home
Assistant media player. Network speakers must also be able to reach the Media Hub
LAN media port.
