// Run with NODE_PATH pointing to an installation containing playwright.
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('pageerror', error => console.error('Browser error:', error));
  let playlists = [], schedules = [], queues = [];
  const output = {entity_id: 'media_player.school', name: 'School speakers', state: 'idle', volume: .4};
  const media = ['Happy song.mp3', 'Recess song.mp3'].map(name => ({source: 'ha', path: name, name, label: name, type: 'audio'}));
  await page.route('http://media-hub.test/**', async route => {
    const req = route.request(), url = new URL(req.url()), body = req.postDataJSON();
    let data = {ok: true};
    if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: fs.readFileSync(path.join(__dirname, '../media_hub/web/index.html'), 'utf8')});
    if (url.pathname === '/playlists.js') return route.fulfill({contentType: 'text/javascript', body: fs.readFileSync(path.join(__dirname, '../media_hub/web/playlists.js'), 'utf8')});
    if (url.pathname === '/api/bootstrap') data = {...data, version: '1.1.0', outputs: [output], playlists, schedules, queues, settings: {time_zone: 'America/Chicago'}};
    else if (url.pathname.startsWith('/api/media')) data.items = media;
    else if (url.pathname === '/api/outputs') data = {...data, outputs: [output], queues};
    else if (url.pathname === '/api/playlists') {
      const playlist = {...body, id: 'lunch'}; playlists.push(playlist); data.playlist = playlist;
    } else if (url.pathname === '/api/playlists/lunch' && req.method() === 'PUT') {
      playlists[0] = {...body, id: 'lunch'}; data.playlist = playlists[0];
    } else if (url.pathname === '/api/playlists/lunch/play') {
      queues = [{entity_id: output.entity_id, target: output.entity_id, playlist_id: 'lunch', name: playlists[0].name, track: 1, total: 2}]; output.state = 'playing';
    } else if (url.pathname === '/api/schedules') {
      body.week = Object.fromEntries(Object.entries(body.week).map(([day, times]) => [day, times.split(', ')]));
      data.schedule = {...body, id: 'schedule1'}; schedules.push(data.schedule);
    } else if (url.pathname === '/api/schedules/schedule1') {
      data.schedule = {...body, id: 'schedule1'}; schedules[0] = data.schedule;
    }
    return route.fulfill({json: data});
  });
  await page.goto('http://media-hub.test/');
  await page.getByRole('button', {name: '♫ Playlists', exact: true}).click();
  await page.getByRole('button', {name: '＋ New playlist'}).click();
  await page.locator('#playlistName').fill('Lunch & Recess');
  await page.locator('#addSong').click();
  await page.locator('#playlistSong').selectOption('ha|Recess song.mp3');
  await page.locator('#addSong').click();
  await page.getByLabel('Move song 2 up', {exact: true}).click();
  await page.locator('#playlistRepeat').check();
  await page.locator('#savePlaylist').click();
  await page.locator('[data-pedit]').waitFor();
  assert.equal(playlists[0].tracks[0].path, 'Recess song.mp3');
  assert.equal(playlists[0].repeat, true);
  await page.locator('[data-pedit]').click();
  assert.equal(await page.locator('#playlistName').inputValue(), 'Lunch & Recess');
  await page.locator('#cancelPlaylist').click();
  await page.locator('[data-pplay]').click();
  await page.getByText('Song 1 of 2 · School speakers', {exact: true}).waitFor();
  await page.locator('[data-page="schedules"]').click();
  await page.locator('#addSchedule').click();
  await page.locator('#schName').fill('School lunch');
  await page.locator('#schMedia').selectOption('playlist|lunch');
  assert.equal(await page.locator('#schAnnounce').isDisabled(), true);
  await page.locator('#schStopTime').fill('12:30');
  await page.locator('#schVolume').fill('40');
  await page.locator('#bulkTimes').fill('12:00');
  await page.locator('#applyBulk').click();
  await page.locator('#saveSchedule').click();
  try { await page.locator('[data-sedit]').waitFor({timeout: 5000}); }
  catch (error) { console.error('Schedule debug:', schedules, await page.locator('#toastRoot').innerText()); await browser.close(); throw error; }
  assert.equal(schedules[0].playlist_id, 'lunch');
  assert.equal(schedules[0].stop_time, '12:30');
  assert.equal(schedules[0].volume, .4);
  assert.equal(Object.keys(schedules[0].week).length, 5);
  await page.locator('[data-sedit]').click();
  assert.equal(await page.locator('#schMedia').inputValue(), 'playlist|lunch');
  assert.equal(await page.locator('#schStopTime').inputValue(), '12:30');
  fs.mkdirSync(path.join(__dirname, '../.test-artifacts'), {recursive: true});
  await page.screenshot({path: path.join(__dirname, '../.test-artifacts/lunch-schedule.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({path: path.join(__dirname, '../.test-artifacts/lunch-schedule-mobile.png'), fullPage: true});
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('Playlist editor, ordering, repeat, playback, weekly schedule, edit, and mobile layout passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
