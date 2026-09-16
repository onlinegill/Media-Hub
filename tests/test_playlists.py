import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'media_hub'))
import app
from aiohttp.test_utils import TestClient, TestServer


class PlaylistTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(app, 'MEDIA_ROOT', root),
                        patch.object(app, 'LIBRARY_ROOT', root),
                        patch.object(app, 'DATA_FILE', root / 'store.json')]
        for p in self.patches:
            p.start()
        for name in ('a.mp3', 'b.mp3'):
            (root / name).write_bytes(b'ID3test')
        self.hub = app.MediaHub()
        app.HUB = self.hub
        self.hub.detected_host = '192.168.1.2'
        self.target = 'media_player.speaker'
        self.player = {'entity_id': self.target, 'state': 'idle',
                       'attributes': {'device_class': 'speaker'}}
        self.hub.ha.states = AsyncMock(side_effect=lambda: [self.player])
        self.hub.ha.call_service = AsyncMock()
        self.playlist = app.sanitize_playlist({'name': 'Lunch', 'tracks': [
            {'source': 'ha', 'path': 'a.mp3'}, {'source': 'library', 'path': 'b.mp3'}]})
        self.hub.store.data['playlists'] = [self.playlist]
        self.client = TestClient(TestServer(app.create_ui_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.hub.close()
        app.HUB = None
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def start(self, **kwargs):
        await self.hub.start_playlist(self.playlist, self.target, **kwargs)
        return self.hub.queues[self.target]

    async def playing(self):
        self.player['state'] = 'playing'
        self.player['attributes']['media_content_id'] = self.hub.queues[self.target]['url']
        await self.hub.playlist_tick()

    async def ended(self):
        self.player['state'] = 'idle'
        await self.hub.playlist_tick()
        await self.hub.playlist_tick()

    async def test_advances_only_after_playing_then_stable_idle(self):
        q = await self.start()
        await self.ended()
        self.assertEqual(q['index'], 0)
        await self.playing()
        self.player['state'] = 'idle'
        await self.hub.playlist_tick()
        self.assertEqual(q['index'], 0)
        await self.hub.playlist_tick()
        self.assertEqual(q['index'], 1)
        self.assertIn('b.mp3', q['url'])
        await self.playing()
        await self.ended()
        self.assertFalse(self.hub.queues)

    async def test_pause_resume_and_stop_do_not_restart(self):
        q = await self.start()
        await self.playing()
        for action in ('pause', 'play', 'stop'):
            response = await self.client.post('/api/control', json={'entity_id': self.target, 'action': action})
            self.assertEqual(response.status, 200)
            if action == 'pause':
                await self.ended()
                self.assertEqual(q['index'], 0)
        await self.ended()
        self.assertFalse(self.hub.queues)

    async def test_repeat_and_next(self):
        self.playlist['repeat'] = True
        q = await self.start()
        await self.playing()
        await self.ended()
        await self.playing()
        await self.ended()
        self.assertEqual(q['index'], 0)
        response = await self.client.post('/api/control', json={'entity_id': self.target, 'action': 'next'})
        self.assertEqual(response.status, 200)
        self.assertEqual(q['index'], 1)

    async def test_deadline_stops_even_while_paused(self):
        q = await self.start(stop_at=datetime.now(ZoneInfo('UTC')) - timedelta(seconds=1))
        q['paused'] = True
        await self.hub.playlist_tick()
        self.hub.ha.call_service.assert_awaited_with('media_stop', {'entity_id': self.target})
        self.assertFalse(self.hub.queues)

    async def test_replacement_does_not_get_stopped_by_old_deadline(self):
        await self.start(stop_at=datetime.now(ZoneInfo('UTC')) - timedelta(seconds=1))
        await self.hub.play_local(self.target, 'ha', 'b.mp3')
        await self.hub.playlist_tick()
        self.assertFalse(self.hub.queues)
        self.assertEqual(self.hub.ha.call_service.await_args.args[0], 'play_media')

    async def test_external_source_and_unavailable_cancel(self):
        await self.start()
        await self.playing()
        self.player['attributes']['media_content_id'] = 'some-other-source'
        await self.hub.playlist_tick()
        self.assertFalse(self.hub.queues)
        await self.start()
        self.player['state'] = 'unavailable'
        await self.hub.playlist_tick()
        self.assertFalse(self.hub.queues)

    async def test_start_timeout_and_missing_next_track(self):
        q = await self.start()
        q['started'] -= 61
        await self.hub.playlist_tick()
        self.assertFalse(self.hub.queues)
        await self.start()
        await self.playing()
        (app.LIBRARY_ROOT / 'b.mp3').unlink()
        await self.ended()
        self.assertFalse(self.hub.queues)

    async def test_playlist_edits_do_not_mutate_running_queue(self):
        q = await self.start()
        self.playlist['tracks'].reverse()
        self.assertEqual(q['tracks'][0]['path'], 'a.mp3')

    async def test_group_member_controls_coordinator_queue(self):
        member = {'entity_id': 'media_player.member', 'state': 'playing',
                  'attributes': {'group_members': [self.target, 'media_player.member']}}
        self.hub.ha.states = AsyncMock(return_value=[self.player, member])
        await self.hub.start_playlist(self.playlist, member['entity_id'])
        self.assertIn(self.target, self.hub.queues)
        await self.client.post('/api/control', json={'entity_id': member['entity_id'], 'action': 'stop'})
        self.assertFalse(self.hub.queues)
        self.hub.ha.call_service.assert_awaited_with('media_stop', {'entity_id': self.target})

    async def test_schedule_validation_and_single_file_compatibility(self):
        payload = {'name': 'Lunch', 'entity_id': self.target, 'playlist_id': self.playlist['id'],
                   'week': {'mon': ['12:00']}, 'stop_time': '12:30', 'volume': 0}
        schedule = app.sanitize_schedule(payload)
        self.assertEqual(schedule['volume'], 0)
        for invalid in ({'stop_time': '11:59'}, {'stop_time': '25:00'}, {'announce': True},
                        {'playlist_id': 'missing'}, {'volume': float('nan')}):
            with self.assertRaises(app.HubError):
                app.sanitize_schedule({**payload, **invalid})
        single = app.sanitize_schedule({**payload, 'playlist_id': '', 'stop_time': '', 'source': 'ha', 'path': 'a.mp3'})
        await self.hub.execute_schedule(single)
        self.assertFalse(self.hub.queues)

    async def test_scheduled_playlist_starts_and_old_schedule_data_loads(self):
        future = (datetime.now(ZoneInfo('UTC')) + timedelta(minutes=1)).strftime('%H:%M')
        schedule = {'name': 'Lunch', 'entity_id': self.target, 'playlist_id': self.playlist['id'], 'stop_time': future}
        if future != '00:00':
            await self.hub.execute_schedule(schedule)
            self.assertEqual(self.hub.queues[self.target]['stop_at'].strftime('%H:%M'), future)
        app.DATA_FILE.write_text(json.dumps({'version': 2, 'schedules': [{'id': 'old'}]}))
        store = app.Store()
        await store.load()
        self.assertEqual(store.data['schedules'], [{'id': 'old'}])
        self.assertEqual(store.data['playlists'], [])

    async def test_api_crud_persistence_and_referenced_delete(self):
        response = await self.client.post('/api/playlists', json={'name': 'Recess', 'tracks': self.playlist['tracks']})
        self.assertEqual(response.status, 200)
        saved = (await response.json())['playlist']
        self.assertIn(saved, json.loads(app.DATA_FILE.read_text())['playlists'])
        response = await self.client.put('/api/playlists/' + saved['id'], json={**saved, 'name': 'Morning recess'})
        self.assertEqual(response.status, 200)
        schedule = await self.client.post('/api/schedules', json={'name': 'Recess', 'entity_id': self.target,
            'playlist_id': saved['id'], 'week': {'mon': ['10:00']}, 'stop_time': '10:15'})
        self.assertEqual(schedule.status, 200)
        response = await self.client.delete('/api/playlists/' + saved['id'])
        self.assertEqual(response.status, 400)
        sid = (await schedule.json())['schedule']['id']
        await self.client.delete('/api/schedules/' + sid)
        response = await self.client.delete('/api/playlists/' + saved['id'])
        self.assertEqual(response.status, 200)

    async def test_invalid_tracks_rejected(self):
        for tracks in ([], [{'source': 'ha', 'path': '../outside.mp3'}], [{'source': 'bad', 'path': 'a.mp3'}],
                       [{'source': 'ha', 'path': 'missing.mp3'}]):
            response = await self.client.post('/api/playlists', json={'name': 'Lunch', 'tracks': tracks})
            self.assertEqual(response.status, 400)

    async def test_deadline_retries_failed_stop_without_advancing(self):
        q = await self.start(stop_at=datetime.now(ZoneInfo('UTC')) - timedelta(seconds=1))
        self.hub.ha.call_service.side_effect = RuntimeError('Temporary network error')
        await self.hub.playlist_tick()
        self.assertIn(self.target, self.hub.queues)
        self.assertEqual(q['index'], 0)
        self.hub.ha.call_service.side_effect = None
        await self.hub.playlist_tick()
        self.assertFalse(self.hub.queues)

    async def test_independent_outputs_and_replacing_queue(self):
        other = {'entity_id': 'media_player.other', 'state': 'idle', 'attributes': {}}
        self.hub.ha.states = AsyncMock(return_value=[self.player, other])
        first = await self.start()
        await self.hub.start_playlist(self.playlist, other['entity_id'])
        await self.start()
        self.assertEqual(len(self.hub.queues), 2)
        self.assertIsNot(self.hub.queues[self.target], first)
        await self.hub.playlist_control(self.target, 'stop')
        self.assertIn(other['entity_id'], self.hub.queues)

    async def test_radio_replaces_queue(self):
        await self.start()
        self.hub._play_radio = AsyncMock(return_value={'mime': 'audio/mpeg'})
        await self.hub.play_radio('station', self.target, '')
        self.assertFalse(self.hub.queues)

    async def test_once_schedule_and_duplicate_minute_guard(self):
        now = datetime.now(ZoneInfo('UTC'))
        schedule = app.sanitize_schedule({'name': 'Recess', 'entity_id': self.target,
            'playlist_id': self.playlist['id'], 'mode': 'once', 'date': now.strftime('%Y-%m-%d'),
            'times': [now.strftime('%H:%M')]})
        self.hub.store.data['schedules'] = [schedule]
        self.hub.execute_schedule = AsyncMock()
        await self.hub.run_due_schedules()
        await asyncio.sleep(0)
        await self.hub.run_due_schedules()
        self.hub.execute_schedule.assert_awaited_once_with(schedule)

    async def test_script_is_served_and_bootstrap_exposes_playlists(self):
        with patch.object(app, 'WEB_ROOT', Path(__file__).resolve().parents[1] / 'media_hub/web'):
            response = await self.client.get('/playlists.js')
            self.assertEqual(response.status, 200)
            self.assertIn('function openPlaylist', await response.text())
        response = await self.client.get('/api/bootstrap')
        self.assertEqual((await response.json())['playlists'], [self.playlist])


if __name__ == '__main__':
    unittest.main()
