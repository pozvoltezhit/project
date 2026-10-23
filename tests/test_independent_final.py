"""Independent release-boundary, graph and raw-ASGI probes; disposable SQL only."""
import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.core import Agent, Principal, Store
from backend.grounding import verified_span
from backend.telemetry import HTTPAccounting, http_requests


@pytest.fixture
def fixture(tmp_path):
    store = Store(str(tmp_path / 'independent.db'))
    p = Principal('independent', 'factory', ('staff',))
    doc = store.ingest('unit', ['Н-17 связан с К-2. При отказе запуск запрещён.'], 'factory', ['staff'])
    agent = Agent(store)
    state = agent.workflow.invoke({'query':'Н-17', 'principal':p, 'session_id':'s', 'request_id':'r'})
    return store, p, doc, state


def test_writer_reserved_before_release_is_observed(fixture):
    store, p, doc, state = fixture
    db = sqlite3.connect(store.path)
    db.execute('BEGIN IMMEDIATE')
    db.execute('DELETE FROM grants WHERE doc_id=?', (doc,))
    started = threading.Event()
    results, errors = [], []
    def release():
        started.set()
        try:
            results.append(store.finalize(p, 'Н-17', 's', 'r', state))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=release)
    thread.start()
    assert started.wait(3)
    db.commit()
    db.close()
    thread.join(5)
    assert not thread.is_alive() and not errors
    assert results[0]['status'] == 'output_blocked'
    assert results[0]['evidence'] == results[0]['graph'] == []
    assert store.verify_audit()


def test_release_reservation_orders_later_raw_writer_and_freezes_result(fixture):
    store, p, doc, state = fixture
    entered, trying, committed = threading.Event(), threading.Event(), threading.Event()
    original = store._append_audit
    errors = []
    def writer():
        assert entered.wait(3)
        try:
            with sqlite3.connect(store.path, timeout=4) as db:
                trying.set()
                db.execute('DELETE FROM grants WHERE doc_id=?', (doc,))
            committed.set()
        except Exception as exc:
            errors.append(exc)
    def audit(*args):
        entered.set()
        assert trying.wait(3)
        assert not committed.is_set()
        return original(*args)
    thread = threading.Thread(target=writer)
    thread.start()
    with patch.object(store, '_append_audit', side_effect=audit):
        result = store.finalize(p, 'Н-17', 's', 'r', state)
    thread.join(5)
    assert not thread.is_alive() and committed.is_set() and not errors
    assert result['status'] == 'answered'
    state['evidence'][0]['quote'] = 'mutated'
    assert result['evidence'][0]['quote'] != 'mutated'
    assert store.allowed(p) == []


def test_slow_sse_client_does_not_hold_sql_writer(fixture):
    import backend.api as api
    store, p, doc, state = fixture
    async def check():
        with patch.object(api, 'agent', Agent(store)):
            response = api.stream(api.Query(question='Н-17'), p)
        # Streaming has not started: SQL release must already be committed.
        with sqlite3.connect(store.path, timeout=.3) as db:
            db.execute('DELETE FROM grants WHERE doc_id=?', (doc,))
        data = [part async for part in response.body_iterator]
        assert len(data) == 1 and 'event: result' in data[0]
        assert json.loads(data[0].split('data: ', 1)[1])['status'] == 'answered'
    asyncio.run(check())


@pytest.mark.parametrize('selection', [
    '120 °C.', 'ГОСТ Р 123.4.', 'п. 3.2.', 'К-2.', 'разрешён.',
])
def test_russian_technical_clipping_never_becomes_released_assertion(selection):
    text = 'Н-17: при исправном К-2 запуск не разрешён. Порог 120 °C. См. п. 3.2. ГОСТ Р 123.4.'
    span = verified_span(text, selection)
    assert span is None or (span['quote'] == text and text[span['start']:span['end']] == text)


def test_mentions_two_hops_tenant_caps_reingest_and_deletion(tmp_path):
    store = Store(str(tmp_path / 'graph.db'))
    p = Principal('a', 'one', ('staff',))
    store.ingest('a', ['Н-17 соединён с К-2.'], 'one', ['staff'])
    second = store.ingest('b', ['К-2 соединён с Д-8.'], 'one', ['staff'])
    store.ingest('c', ['Д-8 имеет порог 120 °C.'], 'one', ['staff'])
    store.ingest('secret', ['К-2 секрет 999.'], 'two', ['staff'])
    seed = [c['id'] for c in store.allowed(p) if c['title'] == 'a']
    zero, _ = store.graph(p, seed, hops=0)
    full, edges = store.graph(p, seed, hops=2)
    assert len(zero) == 1 and {c['title'] for c in full} == {'a', 'b', 'c'}
    assert store.graph(p, seed, hops=999) == (full, edges)
    assert len(store.graph(p, seed, max_chunks=2)[0]) == 2
    old = {c['id'] for c in full if c['title'] == 'b'}
    store.ingest('b', ['К-9 заменён.'], 'one', ['staff'])
    assert not old.intersection(c['id'] for c in store.graph(p, seed)[0])
    with store.connect() as db:
        db.execute('DELETE FROM documents WHERE id=?', (second,))
    assert {c['title'] for c in store.graph(p, seed)[0]} == {'a'}


@pytest.mark.parametrize('failure', ['cancel', 'send_error'])
def test_F06_interrupted_stream_is_not_accounted_as_success(failure):
    def counts():
        return {out:sum(s.value for m in http_requests.collect() for s in m.samples
                       if s.name == 'knowledge_http_requests_total' and s.labels.get('outcome') == out)
                for out in ('success', 'cancelled', 'transport_error')}
    async def app(scope, receive, send):
        await send({'type':'http.response.start', 'status':200})
        if failure == 'cancel':
            raise asyncio.CancelledError()
        await send({'type':'http.response.body', 'body':b'x', 'more_body':False})
    async def send(message):
        if message['type'] == 'http.response.body':
            raise OSError('Disconnected')
    scope = {'type':'http', 'method':'POST', 'route':SimpleNamespace(path='/query/stream')}
    before = counts()
    with pytest.raises(asyncio.CancelledError if failure == 'cancel' else OSError):
        asyncio.run(HTTPAccounting(app)(scope, None, send))
    after = counts()
    assert sum(after.values()) - sum(before.values()) == 1
    assert after['success'] == before['success']
    expected = 'cancelled' if failure == 'cancel' else 'transport_error'
    assert after[expected] - before[expected] == 1


def test_F05_multibody_stream_accounted_once():
    async def app(scope, receive, send):
        await send({'type':'http.response.start', 'status':200})
        for more in (True, True, False):
            await send({'type':'http.response.body', 'body':b'x', 'more_body':more})
    async def send(message):
        pass
    def total():
        return sum(s.value for m in http_requests.collect() for s in m.samples
                   if s.name == 'knowledge_http_requests_total')
    before = total()
    asyncio.run(HTTPAccounting(app)({'type':'http','method':'POST'}, None, send))
    assert total() - before == 1


def test_request_scope_keeps_no_read_snapshot_and_closes_on_failure(fixture):
    store, p, doc, _ = fixture
    with pytest.raises(RuntimeError):
        with store.request_scope():
            # A raw connection can commit while the keeper is attached; a fresh
            # authoritative read observes it even before request_scope exits.
            with sqlite3.connect(store.path, timeout=.3) as db:
                db.execute('DELETE FROM grants WHERE doc_id=?', (doc,))
            db.close()  # SQLite's transaction context does not close the connection.
            assert store.allowed(p) == []
            raise RuntimeError('worker failure')
    # No keeper leaks: the last client checkpoints/removes the WAL on close.
    from pathlib import Path
    assert not Path(store.path+'-wal').exists()
