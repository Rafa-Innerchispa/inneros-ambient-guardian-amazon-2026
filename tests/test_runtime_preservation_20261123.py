"""Existing live pending-claim states must retain the same owner approval gates."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ambient_guardian.ops_decisions import DecisionBroker, TASKS, eligible

# Reuse the in-memory broker double. No real coordination or device calls.
spec=importlib.util.spec_from_file_location('shared_decision_test_doubles',Path(__file__).with_name('test_ops_shared_decisions.py'))
doubles=importlib.util.module_from_spec(spec)
spec.loader.exec_module(doubles)

CLAIM_STATES=['awaiting_codex_claim','awaiting_cursor_claim','awaiting_antigravity_claim',
              'awaiting_gemini_claim','awaiting_chatgpt_claim','awaiting_ide_claim']


@pytest.mark.parametrize('status',CLAIM_STATES)
def test_pending_claim_requires_verified_owner_and_explicit_decision(status):
    db=doubles.DB();calls=[]
    task={'task_id':'ops_123456abcdef','status':status,'assignee':'codex',
          'objective':'read-only verification','payload':{'budget_estimate':{'usd_max':1}}}
    db[TASKS].insert_one(task)
    broker=DecisionBroker(db,execute=lambda *args:calls.append(args),budget_check=lambda t:{'allowed':True})
    assert eligible(task)
    row=broker.register(task,now=100)
    assert row['status']=='pending' and calls==[]
    refused=broker.decide(task['task_id'],row['nonce'],'approve',channel='alexa',verified_owner=False,now=101)
    assert refused['error']=='owner_identity_required' and calls==[]


@pytest.mark.parametrize('status',CLAIM_STATES)
@pytest.mark.parametrize('field,value',[('owner_authorized_at','2026-11-23T20:00:00Z'),('claim_token','already-running')])
def test_authorized_or_claimed_task_is_not_reopened_for_approval(status,field,value):
    task={'task_id':'ops_123456abcdef','status':status,field:value}
    assert not eligible(task)
