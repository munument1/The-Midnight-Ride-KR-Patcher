import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from xml.sax.saxutils import escape

from test_plugin_safety import subrecord, world_plugin


class FinalVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('dotnet'):
            raise unittest.SkipTest('Requires dotnet')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        sources = Path(__file__).resolve().parents[1] / 'tools/TmrPluginTranslator'
        includes = ''.join('<Compile Include="' + escape(str(sources / name), {'"': '&quot;'})
                           + '" />' for name in ('FinalPluginVerifier.cs', 'OriginalTextWriter.cs', 'WorldIndexStripper.cs'))
        (cls.root / 'Harness.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net9.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
            '</PropertyGroup><ItemGroup>' + includes + '</ItemGroup></Project>', encoding='utf-8')
        (cls.root / 'Program.cs').write_text('''
using System.Text.Json;
System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
try {
    var pairs = new[] { new OriginalTextWriter.Pair("WRLD", "FULL", "Old", "새 이름") };
    var result = FinalPluginVerifier.Verify(args[0], args[1], pairs, int.Parse(args[2]));
    System.Console.WriteLine(JsonSerializer.Serialize(result));
} catch (System.Exception error) {
    System.Console.Error.WriteLine(error.Message);
    System.Environment.ExitCode = 1;
}
''', encoding='utf-8')
        run = subprocess.run(['dotnet', 'build', str(cls.root / 'Harness.csproj'), '-v', 'quiet'],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        if run.returncode:
            cls.temp.cleanup()
            raise RuntimeError(run.stdout + run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def verify(self, before, after, expected=1):
        source, output = self.root / 'Probe.esp', self.root / 'saved.esp'
        source.write_bytes(before)
        output.write_bytes(after)
        return subprocess.run(['dotnet', str(self.root / 'bin/Debug/net9.0/Harness.dll'),
            str(source), str(output), str(expected)], capture_output=True,
            text=True, encoding='utf-8', errors='strict', timeout=30)

    def test_only_text_and_world_indexes_change_in_compressed_and_plain_records(self):
        extended = subrecord(b'XXXX', struct.pack('<I', 70000)) + b'MHDT\0\0' + bytes(70000)
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                before = subrecord(b'FULL', b'Old\0') + extended
                before += subrecord(b'OFST', bytes(8)) + subrecord(b'CLSZ', bytes(8))
                after = subrecord(b'FULL', '새 이름'.encode() + b'\0') + extended
                run = self.verify(world_plugin(before, compressed), world_plugin(after, compressed))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(json.loads(run.stdout), {'TextChanges': 1, 'OFST': 1, 'CLSZ': 1, 'ProtectedRecords': 0})

    def test_nontext_change_or_unrelated_field_removal_is_rejected(self):
        before = world_plugin(subrecord(b'FULL', b'Old\0') + subrecord(b'ZZZZ', bytes(8)))
        translated = subrecord(b'FULL', '새 이름'.encode() + b'\0')
        for rest in (b'', subrecord(b'ZZZZ', b'changed\0')):
            with self.subTest(rest=rest):
                self.assertNotEqual(self.verify(before, world_plugin(translated + rest)).returncode, 0)

    def test_stale_world_index_is_rejected(self):
        index = subrecord(b'OFST', bytes(8))
        run = self.verify(world_plugin(subrecord(b'FULL', b'Old\0') + index),
                          world_plugin(subrecord(b'FULL', '새 이름'.encode() + b'\0') + index))
        self.assertNotEqual(run.returncode, 0)

    def test_changed_header_and_zimonja_record_are_rejected(self):
        before = world_plugin(subrecord(b'FULL', b'Old\0'))
        after = bytearray(world_plugin(subrecord(b'FULL', '새 이름'.encode() + b'\0')))
        after[18] = 1  # TES4 non-size header byte.
        self.assertNotEqual(self.verify(before, bytes(after)).returncode, 0)
        edid = subrecord(b'EDID', b'ModOwnedZimonjaMarker\0')
        run = self.verify(world_plugin(edid + subrecord(b'FULL', b'Old\0')),
                          world_plugin(edid + subrecord(b'FULL', '새 이름'.encode() + b'\0')))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('Protected Zimonja', run.stderr)
