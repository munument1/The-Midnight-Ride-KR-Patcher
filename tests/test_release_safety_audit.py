from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_release_output import protected_zimonja


def sub(signature, value):
    return signature + struct.pack('<H', len(value)) + value


class ProtectedRecordAuditTests(unittest.TestCase):
    def test_master_indices_and_mod_owned_editor_id(self):
        records = {
            ('TES4', '00000000'): sub(b'MAST', b'Other.esm\0') + sub(b'MAST', b'Fallout4.esm\0'),
            ('LCTN', '01055402'): sub(b'FULL', b'Outpost Zimonja\0'),
            ('CELL', '0100DCEC'): b'',
            ('REFR', '0102495A'): b'',
            ('REFR', '02000801'): sub(b'EDID', b'UFO4POutpostZimonjaFTMarker\0'),
            ('LCTN', '00055402'): sub(b'FULL', b'Unrelated master record\0'),
            ('LCTN', '02055402'): sub(b'FULL', b'Unrelated mod record\0'),
        }
        self.assertEqual(set(protected_zimonja(records, 'Example.esp')), {
            ('LCTN', '01055402'), ('CELL', '0100DCEC'),
            ('REFR', '0102495A'), ('REFR', '02000801'),
        })
