#!/usr/bin/env python3
"""Exercise BD-J image packaging without invoking the CE image build."""
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'projects/Amlogic-ce/packages/mediacenter/bdj-runtime/package.mk'
VERSION = re.search(r'^PKG_VERSION="([^"]+)"',
                    (ROOT / 'packages/multimedia/libbluray/package.mk').read_text(), re.M)[1]
JARS = [f'libbluray-j2se-{VERSION}.jar', f'libbluray-awt-j2se-{VERSION}.jar']


class RuntimePackaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'java-package'
        (self.source / 'usr/share/java').mkdir(parents=True)
        self.image = self.root / 'image'

    def install(self, jars):
        for name in jars:
            (self.source / 'usr/share/java' / name).write_bytes(b'compiled jar fixture')
        return subprocess.run(['bash', '-c', '''
get_pkg_version() { echo "$BDJ_VERSION"; }
get_install_dir() { echo "$BDJ_SOURCE"; }
. "$BDJ_PACKAGE"
makeinstall_target
'''], env={'PATH': '/usr/bin:/bin', 'INSTALL': str(self.image),
           'BDJ_VERSION': VERSION, 'BDJ_SOURCE': str(self.source),
           'BDJ_PACKAGE': str(PACKAGE)}, capture_output=True, text=True)

    def test_pair_and_addon_classpath_override(self):
        result = self.install(JARS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in (self.image / 'usr/share/java').iterdir()), sorted(JARS))
        script = self.image / 'usr/lib/coreelec/bdj-runtime.sh'
        result = subprocess.run(['sh', '-c', '. "$1"; printf "%s" "$LIBBLURAY_CP"', 'sh', str(script)],
                                env={'LIBBLURAY_CP': '/storage/.kodi/addons/tools.jre.zulu/'},
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, '/usr/share/java/')

    def test_missing_either_jar_fails_before_install(self):
        for missing in JARS:
            with self.subTest(missing=missing):
                for p in (self.source / 'usr/share/java').iterdir():
                    p.unlink()
                result = self.install([p for p in JARS if p != missing])
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.image.exists())

    def test_stale_pair_is_not_a_substitute(self):
        result = self.install(['libbluray-j2se-1.3.4.jar', 'libbluray-awt-j2se-1.3.4.jar'])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.image.exists())


if __name__ == '__main__':
    unittest.main()
