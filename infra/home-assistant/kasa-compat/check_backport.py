"""Offline regressions against the actual installed dependency, with synthetic data."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from kasa.deviceconfig import DeviceConfig, DeviceConnectionParameters
from kasa.iot import IotStrip
from kasa.transports import KlapTransport, KlapTransportV2, XorTransport
import kasa.device_factory as stock
from kasa_backport_20261124 import patched_source


class Backport(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'factory.py'
        source=Path(os.environ.get('KASA_STOCK_SOURCE',stock.__file__))
        self.path.write_text(patched_source(source.read_text()))
        original=importlib.util.spec_from_file_location('kasa._inneros_original_factory',source)
        self.original=importlib.util.module_from_spec(original);original.loader.exec_module(self.original)
        spec=importlib.util.spec_from_file_location('kasa._inneros_test_factory',self.path)
        self.factory=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.factory)

    def tearDown(self):
        self.temp.cleanup()

    def config(self,family='IOT.SMARTPLUGSWITCH',encryption='KLAP',version=2):
        return DeviceConfig('127.0.0.1',connection_type=DeviceConnectionParameters.from_values(
            family,encryption,login_version=version))

    async def test_advertised_v2_selects_v2_instead_of_stock_v1(self):
        cfg=self.config()
        old=self.original.get_protocol(cfg);new=self.factory.get_protocol(cfg)
        try:
            self.assertIs(type(old._transport),KlapTransport)
            self.assertIs(type(new._transport),KlapTransportV2)
        finally:await old.close();await new.close()

    async def test_legacy_and_smart_protocols_are_preserved(self):
        for cfg,expected in [(self.config(version=1),KlapTransport),
                             (self.config(encryption='XOR',version=None),XorTransport),
                             (self.config(family='SMART.TAPOPLUG'),KlapTransportV2)]:
            protocol=self.factory.get_protocol(cfg)
            try:self.assertIs(type(protocol._transport),expected)
            finally:await protocol.close()

    async def test_authenticated_strip_is_not_collapsed_to_master_plug(self):
        cfg=self.config();protocol=self.factory.get_protocol(cfg)
        info={'system':{'get_sysinfo':{'type':'IOT.SMARTPLUGSWITCH','model':'HS300(US)',
              'alias':'Synthetic strip','deviceId':'synthetic','mac':'00:11:22:33:44:55',
              'children':[{'id':str(i),'alias':'Synthetic '+str(i),'state':0} for i in range(6)]}}}
        try:
            with patch.object(protocol,'query',AsyncMock(return_value=info)) as query, \
                 patch.object(IotStrip,'update',AsyncMock()):
                device=await self.factory._connect(cfg,protocol)
                self.assertIsInstance(device,IotStrip)
                query.assert_awaited_once_with(self.factory.GET_SYSINFO_QUERY)
        finally:await protocol.close()

    async def test_unreviewed_source_is_rejected(self):
        with self.assertRaises(ValueError):patched_source('unreviewed source')

    async def test_candidate_image_installs_the_exact_reviewed_module(self):
        if os.environ.get('KASA_EXPECT_PATCHED')=='1':
            self.assertEqual(Path(stock.__file__).read_bytes(),self.path.read_bytes())


if __name__=='__main__':unittest.main()
