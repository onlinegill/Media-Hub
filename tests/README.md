# Playlist tests

Install `aiohttp` in your Python environment, then run from the repository root:

```sh
python -m unittest discover -s tests -v
```

These tests use temporary media files and a simulated Home Assistant client. They
exercise the HTTP API, saved data migration, scheduling, queue transitions,
speaker groups, independent outputs, cancellation, deadlines, and failure handling.

For the browser flow, install the Node `playwright` package and its Chromium
browser, then run:

```sh
node tests/playlists-ui.cjs
```

Alternatively set `PLAYWRIGHT_CHANNEL=msedge` or `chrome` to use an installed
browser. The test mocks the HTTP API and checks playlist creation, ordering,
repeat, playback, schedule creation/editing, and mobile layout. Screenshots are
written to the ignored `.test-artifacts` directory.

Before release, test with the school's Home Assistant speaker integration: play
two songs, confirm automatic advancement, pause/resume, stop, and run a short
schedule with a stop time. Confirm it continues when the dashboard is closed.
