import os
from pathlib import Path
import sys
import tempfile
import unittest
from tools.testbench.launch import working_directory
from tools.testbench.session import EngineProfile, HubSession, EngineExited


class LaunchTests(unittest.TestCase):
    def test_scan_configuration_discovery_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'src').mkdir(); (root/'scan.ini').write_text('variant=frisian')
            executable=root/'src/scan.exe'
            self.assertEqual(working_directory(executable),str(root))
            self.assertEqual(working_directory(executable,root/'src'),str(root/'src'))
            (root/'src/scan.ini').write_text('variant=frisian')
            self.assertEqual(working_directory(executable),str(root/'src'))

    def test_engine_stderr_survives_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            peer=Path(tmp)/'failure.py'; peer.write_text('import sys\nprint(\'unable to open scan.ini\',file=sys.stderr,flush=True)\nsys.exit(2)\n')
            session=HubSession(EngineProfile(sys.executable,(str(peer),)))
            with self.assertRaisesRegex(EngineExited,'unable to open scan.ini'):
                session.start()

    @unittest.skipUnless(os.environ.get('SCAN_TEST_ENGINE'),'local Scan engine required')
    def test_real_scan_starts_without_explicit_cwd(self):
        with HubSession(EngineProfile(os.environ['SCAN_TEST_ENGINE'])) as session:
            session.start({'variant':'frisian','book':False,'bb-size':0,'threads':1})
            session.begin_search('W'+'b'*20+'e'*10+'w'*20,level=[('depth',2)])
            self.assertTrue(session.wait_done().get('move'))
