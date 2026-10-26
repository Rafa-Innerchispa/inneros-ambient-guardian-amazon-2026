from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ambient_guardian import mobile_approval as mobile
from ambient_guardian.orchestration import localize_alexa_result


class Rows:
    def __init__(self, row):
        self.row = deepcopy(row)

    def find_one(self, query):
        return deepcopy(self.row) if all(self.row.get(k) == v for k, v in query.items()) else None

    def update_one(self, query, update):
        if not all(self.row.get(k) == v for k, v in query.items()):
            return SimpleNamespace(modified_count=0)
        self.row.update(update['$set'])
        return SimpleNamespace(modified_count=1)


@pytest.fixture
def row():
    return {'_id': 1, 'task_id': 'ops_abcdef123456', 'owner_id': 'owner',
            'status': 'awaiting_owner_approval', 'nonce': 'bound-secret',
            'action_id': 'action-123', 'action_type': 'voiceops_owner_mobile_callback',
            'target_alias': 'voiceops.owner.mobile',
            'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()}


def event(owner='owner', nonce='bound-secret', decision='approve'):
    return {'context': {'user_id': owner}, 'data': {
        'task_id': 'ops_abcdef123456', 'nonce': nonce, 'decision': decision}}


def test_owner_decision_cannot_be_forged_replayed_or_reversed(row):
    rows = Rows(row)
    assert not mobile.decide(rows, event(owner='another-admin'), 'owner')
    assert not mobile.decide(rows, event(nonce='another-request'), 'owner')
    assert mobile.decide(rows, event(), 'owner')
    assert not mobile.decide(rows, event(), 'owner')
    assert not mobile.decide(rows, event(decision='cancel'), 'owner')
    assert rows.row['status'] == 'approved'
    assert rows.row['authorization_channel'] == mobile.CHANNEL


def test_expired_request_never_authorizes(row):
    row['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    assert not mobile.decide(Rows(row), event(), 'owner')
    assert len(mobile.cards_for(row)) == 1


def test_runtime_proof_binds_actual_callback_and_is_consumed_once(row, monkeypatch):
    rows = Rows(row)
    assert mobile.decide(rows, event(), 'owner')
    monkeypatch.setattr(mobile, 'collection', lambda: rows)
    payload = {'approval_id': row['task_id'], 'correlation_id': 'other-action'}
    assert mobile.consume(payload) == {'approved': False}
    payload['correlation_id'] = row['action_id']
    assert mobile.consume(payload) == {'approved': True}
    assert mobile.consume(payload) == {'approved': False}


def test_internal_proof_cannot_authorize_mobile_call(row, monkeypatch):
    row.update(action_type='voiceops_owner_callback', target_alias='voiceops.owner')
    rows = Rows(row)
    assert mobile.decide(rows, event(), 'owner')
    monkeypatch.setattr(mobile, 'collection', lambda: rows)
    payload = {'approval_id': row['task_id'], 'correlation_id': row['action_id'],
               'target_alias': 'voiceops.owner.mobile'}
    assert not mobile.consume(payload)['approved']
    payload['target_alias'] = 'voiceops.owner'
    assert mobile.consume(payload)['approved']


@pytest.mark.parametrize('locale,word', [('es-US', 'Autorízala'), ('en-US', 'authorize')])
def test_mobile_instructions_do_not_send_owner_to_whatsapp(locale, word):
    result = {'prepared_action': {'approval_channel': mobile.CHANNEL,
              'approval_delivery': 'pending', 'target_label': 'Living'},
              'response': {'answer': 'WhatsApp'}}
    answer = localize_alexa_result(result, locale)['response']['answer']
    assert word in answer
    assert 'WhatsApp' not in answer
