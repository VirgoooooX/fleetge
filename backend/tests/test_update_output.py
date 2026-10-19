import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.models import AutoUpdateRun
from app.routers import stacks
from app.services import auto_update


class UpdateOutputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.manager = auto_update.AutoUpdateManager()
        self.patches = [patch.object(auto_update, 'engine', self.engine), patch.object(stacks, 'auto_update_manager', self.manager)]
        for p in self.patches:
            p.start()
        with Session(self.engine) as session:
            run = AutoUpdateRun(host_id='nas', stack_name='app', request_id='request', source='manual', status='running')
            session.add(run)
            session.commit()
            session.refresh(run)
            self.run_id = run.id

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()

    async def test_viewer_disconnect_does_not_cancel_execution_and_new_viewer_replays(self):
        release = asyncio.Event()
        async def execute():
            self.manager._append_run_log(self.run_id, '\x1b[32mPull complete\x1b[0m\r\n')
            await release.wait()
            self.manager._append_run_log(self.run_id, 'Container app Started\r\n')
            self.manager.finish(self.run_id, 'success', 'verified')
        task = asyncio.create_task(execute())
        await asyncio.sleep(0)
        viewer = stacks._stream_update_run('nas', 'request', 'app')
        first = await anext(viewer)
        self.assertIn('Pull complete', first)
        self.assertIn('\\u001b', first)
        await viewer.aclose()
        self.assertFalse(task.done())
        release.set()
        await task
        replay = [event async for event in stacks._stream_update_run('nas', 'request', 'app')]
        self.assertIn('Container app Started', ''.join(replay))
        self.assertIn('"outcome": "success"', replay[-1])
        self.assertEqual(sum('Pull complete' in event for event in replay), 1)

    async def test_terminal_result_comes_after_final_output_and_cursor_skips_old_chunks(self):
        self.manager._append_run_log(self.run_id, 'Pulling\r\n')
        self.manager._append_run_log(self.run_id, 'Started\r\n')
        self.manager.finish(self.run_id, 'failed', 'health failed')
        events = [event async for event in stacks._stream_update_run('nas', 'request', 'app', after=1)]
        self.assertNotIn('Pulling', ''.join(events))
        self.assertIn('Started', events[0])
        self.assertIn('"outcome": "failed"', events[-1])

    async def test_old_record_without_raw_buffer_replays_plain_tail(self):
        self.manager._append_run_log(self.run_id, 'old log\n')
        self.manager.finish(self.run_id, 'uncertain', 'backend restarted')
        self.manager.output.clear()
        events = [event async for event in stacks._stream_update_run('nas', 'request', 'app')]
        self.assertIn('old log', events[0])
        self.assertIn('"outcome": "uncertain"', events[-1])
