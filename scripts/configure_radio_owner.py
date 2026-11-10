"""Reuse the canonical Companion worker owner; never invent a second authority."""
from pathlib import Path
import json
import re
import shlex

source=Path.home()/'.config/systemd/user/inneros-mobile-approvals.service'
owner=None
for line in source.read_text().splitlines():
    if line.startswith('Environment='):
        for assignment in shlex.split(line.split('=',1)[1]):
            if assignment.startswith('AMBIENT_GUARDIAN_MOBILE_OWNER_ID='):
                owner=assignment.split('=',1)[1]
if owner is None or not re.fullmatch('[a-f0-9]{32}',owner):
    raise RuntimeError('Canonical authenticated Companion owner was not found')
path=Path.home()/'.config/ambient-guardian/radio-owner.env'
path.write_text('AMBIENT_GUARDIAN_MOBILE_OWNER_ID='+owner+'\n');path.chmod(0o600)
print(json.dumps({'owner_bound_to_existing_companion_worker':True,'credential_values_printed':False}))
