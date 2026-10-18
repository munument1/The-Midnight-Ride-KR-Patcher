"""Independently verify headers, record order and non-text data in an Output."""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tmrkr
from tmrkr_output import _provider_target
from tmrkr_plugin_safety import _subrecords, offset_tables
from compare_plugin_save import inspect

# Fallout 4 display text signatures observed in the reviewed release mappings.
TEXT_FIELDS = {b'NAM1', b'FULL', b'NNAM', b'CNAM', b'ITXT', b'DESC', b'UNAM',
               b'RNAM', b'WNAM', b'BTXT', b'NAM0', b'SHRT', b'DNAM', b'ATTX',
               b'ONAM', b'BPTN', b'EPF2', b'ANAM', b'RDMP'}


def headers(path):
    data = path.read_bytes()
    pos, result = 0, []
    while pos < len(data):
        header = data[pos:pos + 24]
        size = struct.unpack_from('<I', header, 4)[0]
        result.append(header[:4] + header[8:])  # Size is the only allowed header change.
        pos += 24 if header[:4] == b'GRUP' else 24 + size
    return result


def text(value):
    try:
        return value.rstrip(b'\0').decode('utf-8').replace('\r\n', '\n')
    except UnicodeDecodeError:
        return value.rstrip(b'\0').decode('cp1252').replace('\r\n', '\n')


def pairs(document):
    return {(r['source'].replace('\r\n', '\n'), r['dest'].replace('\r\n', '\n'))
            for r in document['mappings']}


def verify(output, data):
    report = json.loads((output / 'TMR-Korean-Patcher-report.json').read_text(encoding='utf-8'))
    installation = tmrkr.Installation(Path(report['mo2_root']), report['profile'])
    bank = pairs(json.loads((data / 'fallback/fallout4-base-dlc-fallback.json').read_text(encoding='utf-8-sig')))
    catalog = json.loads((data / 'catalog.json').read_text(encoding='utf-8-sig'))
    entries = {e['name'].casefold(): e for e in catalog['plugins']}
    results = []
    for row in report['plugins']:
        source = installation.source(row['plugin'])
        if tmrkr.sha256(source) != row['source_sha256']:
            raise ValueError(f"Source changed: {row['plugin']}")
        if not row['changed']:
            continue
        approved = bank.copy()
        entry = entries[row['plugin'].casefold()]
        if entry.get('direct_mapping'):
            approved.update(pairs(json.loads((data / entry['direct_mapping']).read_text(encoding='utf-8-sig'))))
        target = _provider_target(output, {'provider': row['provider'], 'path': row['relative_path']})
        _, original, _, _ = inspect(source)
        _, translated, _, _ = inspect(target)
        if headers(source) != headers(target) or list(original) != list(translated):
            raise ValueError(f"Header or record order changed: {row['plugin']}")
        changes = Counter()
        for key, body in original.items():
            left = list(_subrecords(body))
            right = list(_subrecords(translated[key]))
            if key[0] == 'WRLD':
                left = [p for p in left if p[0] not in {b'OFST', b'CLSZ'}]
            if len(left) != len(right):
                raise ValueError(f"Field count changed: {row['plugin']} {key}")
            for (sig, before), (other, after) in zip(left, right):
                if sig != other:
                    raise ValueError(f"Field order changed: {row['plugin']} {key}")
                if before == after:
                    continue
                if sig not in TEXT_FIELDS or not before.endswith(b'\0') or not after.endswith(b'\0'):
                    raise ValueError(f"Non-text changed: {row['plugin']} {key} {sig}")
                translated_text = after[:-1].decode('utf-8').replace('\r\n', '\n')
                before_text = text(before)
                if before_text != translated_text and (before_text, translated_text) not in approved:
                    raise ValueError(f"Unapproved text replacement: {row['plugin']} {key} {sig}")
                changes[sig.decode()] += 1
            if key in {('LCTN', '00055402'), ('REFR', '0002495A'), ('CELL', '0000DCEC')}:
                if body != translated[key]:
                    raise ValueError(f"Protected Zimonja record changed: {row['plugin']} {key}")
        if offset_tables(target):
            raise ValueError(f"World index remains: {row['plugin']}")
        results.append({'plugin': row['plugin'], 'text_fields': dict(changes),
                        'headers_preserved': True, 'records_preserved': True,
                        'nontext_preserved': True})
    return results


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--data', type=Path, required=True)
    args = ap.parse_args()
    results = verify(args.output, args.data)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Verified {len(results)} plugins; {sum(sum(r['text_fields'].values()) for r in results)} text fields")
