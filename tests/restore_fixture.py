"""Standard-library-only restore tests; run on Debian, never against real roots."""
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RestoreFixture(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader('helper',str(Path(__file__).resolve().parent.parent/'deploy'/'ps5-panel-helper'))
        spec = importlib.util.spec_from_loader(loader.name,loader)
        self.helper = importlib.util.module_from_spec(spec)
        loader.exec_module(self.helper)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base/'vanilla';self.root.mkdir()
        (self.root/'server.properties').write_text('enable-rcon=true\nrcon.port=25575\nrcon.password=CURRENT\n')
        (self.root/'old-world').write_text('original world')
        self.backups = self.base/'backups';self.backups.mkdir()
        self.setdir = self.backups/'backup-test';self.setdir.mkdir()
        (self.setdir/'.complete').touch()
        self.archive = self.setdir/'vanilla.tar.gz'
        self.helper.ROOTS = {'survival':self.root}
        self.helper.BACKUPS = self.backups
        self.active = True
        self.fail_start = False

    def tearDown(self):
        self.temporary.cleanup()

    def make_archive(self,evil=None):
        with tarfile.open(self.archive,'w:gz') as archive:
            items = {'./server.jar':b'jar fixture','./server.properties':b'rcon.password=OLD\nmotd=Restored\n','./world/level.dat':b'fixture world'}
            if evil:
                items[evil]=b'escape'
            for name,body in items.items():
                member=tarfile.TarInfo(name);member.size=len(body)
                archive.addfile(member,io.BytesIO(body))

    def control(self,*args):
        if args[0]=='stop':
            self.active=False
        if args[0]=='start':
            if self.fail_start:
                self.fail_start=False
                raise RuntimeError('Simulated start failure')
            self.active=True
        return ''

    def process(self,args,**kwargs):
        if 'is-active' in args:
            return subprocess.CompletedProcess(args,0 if self.active else 3)
        return subprocess.CompletedProcess(args,0)

    def invoke(self):
        # No system service/permissions are changed: all side effects are mocked.
        account=type('Account',(),{'pw_uid':os.getuid(),'pw_gid':os.getgid()})()
        with patch.object(self.helper,'ctl',side_effect=self.control),patch.object(self.helper.subprocess,'run',side_effect=self.process),patch.object(self.helper.pwd,'getpwnam',return_value=account),patch.object(self.helper.os,'chown'):
            self.helper.restore('survival','backup-test/vanilla.tar.gz')

    def test_success_retains_rollback_and_current_rcon(self):
        self.make_archive();self.invoke()
        self.assertEqual((self.root/'world/level.dat').read_bytes(),b'fixture world')
        self.assertIn('rcon.password=CURRENT',(self.root/'server.properties').read_text())
        rollback=list(self.base.glob('.panel-rollback-*'))
        self.assertEqual(len(rollback),1)
        self.assertEqual((rollback[0]/'old-world').read_text(),'original world')
        self.assertTrue(self.active)

    def test_traversal_preserves_original(self):
        self.make_archive('../escape')
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual((self.root/'old-world').read_text(),'original world')
        self.assertFalse((self.base/'escape').exists())
        self.assertTrue(self.active)

    def test_start_failure_rolls_back(self):
        self.make_archive();self.fail_start=True
        with self.assertRaises(RuntimeError):self.invoke()
        self.assertEqual((self.root/'old-world').read_text(),'original world')
        self.assertTrue(self.active)

    def test_incomplete_set_rejected(self):
        self.make_archive();(self.setdir/'.complete').unlink()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual((self.root/'old-world').read_text(),'original world')


if __name__=='__main__':
    unittest.main(verbosity=2)
