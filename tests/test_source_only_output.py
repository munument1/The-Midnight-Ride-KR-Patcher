"""Exercise real runtime generation with matching and updated installed plugins."""
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

import tmrkr
from tmrkr_output import build_output
from test_translation_backend import fixture, row, record, sub


class InstalledSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = Path(__file__).resolve().parents[1] / 'build/Backend/TmrPluginTranslator.exe'
        if not cls.backend.is_file():
            raise unittest.SkipTest('Publish backend to build/Backend first')

    def exercise(self, original, current):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mo2, data, base = root/'MO2', root/'data', root/'base'
            game = root/'Game'
            (game/'Data').mkdir(parents=True)
            (game/'Data/Fallout4.esm').write_bytes(fixture())
            (mo2/'profiles/Default').mkdir(parents=True)
            (mo2/'profiles/Default/modlist.txt').write_text('+Test Mod\n')
            (mo2/'profiles/Default/plugins.txt').write_text('*Synthetic.esp\n')
            (mo2/'ModOrganizer.ini').write_text(
                '[General]\ngameName=Fallout 4\nselected_profile=Default\ngamePath='+game.as_posix()+'\n')
            (mo2/'mods/Test Mod').mkdir(parents=True)
            source = mo2/'mods/Test Mod/Synthetic.esp'
            source.write_bytes(current)
            for name in ('Strings', 'Interface'):
                (base/name).mkdir(parents=True)
            (base/'Strings/test_en.strings').write_bytes(b'base resource')
            (data/'Backend').mkdir(parents=True)
            shutil.copy2(self.backend, data/'Backend/TmrPluginTranslator.exe')
            (data/'fallback').mkdir()
            (data/'fallback/fallout4-base-dlc-fallback.json').write_text(json.dumps({'schema_version':1,'mappings':[]}))
            (data/'direct.json').write_text(json.dumps({'schema_version':1,'target':'Synthetic.esp',
                'mappings':[row('055403','Safe Location','안전한 장소')]}), encoding='utf-8')
            # A legacy catalog and valid-looking cached file must never bypass generation.
            cached = data/'cached.esp'
            cached.write_bytes(b'OBSOLETE COMPLETE PLUGIN')
            import hashlib
            (data/'catalog.json').write_text(json.dumps({'schema_version':1,'plugins':[{
                'name':'Synthetic.esp','source_sha256':hashlib.sha256(original).hexdigest(),
                'plugin_policy_version':6,'baseline_status':'translated','changed':999,
                'direct_mapping':'direct.json','payload':'cached.esp',
                'payload_sha256':tmrkr.sha256(cached),'payload_encoding':'utf-8',
                'text_roundtrip_verified':True,'final_binary_verified':True,
                'world_index_policy':'strip_wrld_ofst_clsz_v1'}]}))
            report = build_output(mo2,base,data,root/'Output')
            self.assertEqual(source.read_bytes(),current)
            target=root/'Output/mods/Test Mod/Synthetic.esp'
            result=report['plugins'][0]
            self.assertNotEqual(result['status'],'exact_payload')
            if target.exists():
                self.assertEqual(result['status'],'translated_current_source')
                self.assertTrue(result['detail']['final_binary_verified'])
                self.assertNotEqual(target.read_bytes(),cached.read_bytes())
                return target.read_bytes()
            self.assertEqual(result['changed'],0)
            return None

    def test_matching_legacy_hash_still_translates_installed_source(self):
        result=self.exercise(fixture(),fixture())
        self.assertIn('안전한 장소'.encode(),result)

    def test_updated_source_keeps_added_record_and_new_header(self):
        original=fixture()
        added=record(b'LCTN',0x55404,sub(b'EDID',b'NewVersionRecord\0')+sub(b'FULL',b'New untranslated location\0'))
        updated=bytearray(original+added)
        struct.pack_into('<I',updated,20,123)  # source header revision
        group=updated.index(b'GRUP')
        struct.pack_into('<I',updated,group+4,len(updated)-group)
        result=self.exercise(original,bytes(updated))
        self.assertIn(added,result)
        self.assertEqual(result[20:24],bytes(updated[20:24]))
        self.assertIn('안전한 장소'.encode(),result)

    def test_changed_original_text_is_not_replaced_by_old_translation(self):
        changed=fixture().replace(b'Safe Location',b'New! Location')
        self.assertIsNone(self.exercise(fixture(),changed))
