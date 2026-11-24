"""Guarded backport for python-kasa 0.10.2 IOT KLAP-v2 authentication/strips.

Based on the upstream root causes in python-kasa issues #1648 and #1740,
and the sysinfo classification fix in upstream PR #1769. No credentials,
network requests or device commands are part of this patch application.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import py_compile

STOCK_SHA256 = '0aef3ba22308b9531cc0b05cf01601e105e28c1f4d8334307f437bc2e59a2437'
MARKER = '# InnerOS bounded python-kasa 0.10.2 KLAP-v2 backport'


def patched_source(stock: str) -> str:
    if hashlib.sha256(stock.encode()).hexdigest() != STOCK_SHA256:
        raise ValueError('Unexpected source; review the vendor version instead of overwriting it')
    before = '        "IOT.KLAP": (IotProtocol, KlapTransport),'
    after = '''        "IOT.KLAP": (
            IotProtocol,
            KlapTransportV2 if ctype.login_version == 2 else KlapTransport,
        ),'''
    classify = '        protocol._transport, XorTransport\n'
    assert stock.count(before) == 1 and stock.count(classify) == 1
    result = stock.replace(before, after).replace(
        classify, '        protocol._transport, (XorTransport, KlapTransport)\n'
    )
    return result + '\n' + MARKER + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args()
    if importlib.metadata.version('python-kasa') != '0.10.2':
        raise SystemExit('Requires reviewed python-kasa 0.10.2; no changes made')
    spec = importlib.util.find_spec('kasa.device_factory')
    assert spec and spec.origin
    path = Path(spec.origin)
    stock = path.read_text()
    if stock.endswith('\n' + MARKER + '\n'):
        # A marker alone is not sufficient: reconstruct and verify the stock hash.
        reverse = stock.removesuffix('\n' + MARKER + '\n').replace(
            '''        "IOT.KLAP": (
            IotProtocol,
            KlapTransportV2 if ctype.login_version == 2 else KlapTransport,
        ),''', '        "IOT.KLAP": (IotProtocol, KlapTransport),'
        ).replace('        protocol._transport, (XorTransport, KlapTransport)\n',
                  '        protocol._transport, XorTransport\n')
        assert patched_source(reverse) == stock
        print(json.dumps({'status':'already_applied','sha256':hashlib.sha256(stock.encode()).hexdigest()}))
        return
    updated = patched_source(stock)
    compile(updated, str(path), 'exec')
    if args.apply:
        if args.backup_dir:
            args.backup_dir.mkdir(parents=True,exist_ok=False)
            (args.backup_dir/'device_factory.py').write_text(stock)
        path.write_text(updated)
        py_compile.compile(str(path), doraise=True)
    print(json.dumps({'status':'applied' if args.apply else 'preview',
                      'stock_sha256':STOCK_SHA256,
                      'patched_sha256':hashlib.sha256(updated.encode()).hexdigest()}))


if __name__ == '__main__':
    main()
