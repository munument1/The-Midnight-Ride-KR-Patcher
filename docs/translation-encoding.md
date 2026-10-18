# 번역 문자열 저장과 검증

PR #1(manbokgo)의 인코딩 수정·테스트를 v1.0.2 원본 보존 백엔드에 통합했습니다.

- ESP/ESM: 입력은 엄격한 UTF-8을 먼저 읽고 CP1252로 대체합니다. 출력 표시 문자열은 UTF-8입니다.
- Interface/Translations: `_en` 이름과 줄바꿈을 유지하며 UTF-16 LE BOM으로 저장합니다.
- MCM JSON: UTF-8로 저장합니다.
- `TranslatedString`만 번역 후보로 취급합니다. 대사와 동일한 영어가 들어 있어도 ScriptNotes 등 일반 문자열은 치환하지 않습니다.
- 원본 레코드·필드·헤더·순서를 보존하는 OriginalTextWriter와 WRLD OFST/CLSZ 제거, 지몬자 제외 정책을 유지합니다.
- localized 플러그인은 `skipped_localized_strings`로 명시적으로 제외합니다. PR의 localized 재직렬화 경로는 원본 보존 검증이 별도로 필요하므로 채택하지 않았습니다.

exact payload는 현재 정책 5와 원본 SHA-256이 일치하고 `payload_encoding: "utf-8"`, `text_roundtrip_verified: true`가 모두 있어야 사용합니다. 파일이 없거나 검증 정보가 없으면 사전 경로로 전환합니다. 해시 불일치는 오류로 중단합니다. WRLD 인덱스 잔존 검사도 유지합니다.

이미 설치 파일에 `???`가 저장됐다면 영문 원본을 복원하고 Output을 다시 생성해야 합니다. 변경 0개는 입력이 정상이라는 증거가 아닙니다.

테스트는 실제 백엔드와 독립 바이너리 파서를 사용합니다.

```powershell
dotnet build tools/TmrPluginTranslator
$env:TMR_TRANSLATOR = (Resolve-Path tools/TmrPluginTranslator/bin/Debug/net9.0/TmrPluginTranslator.dll).Path
$env:TMR_PRP_SAMPLE_DIR = 'C:/Modlists/TMR/mods/Previsibines Repair Pack'
python -m unittest discover -s tests -v
```

검사 범위는 한국어 direct/fallback 저장, CP1252 문장부호, 압축 레코드, 재번역, 반복 퀘스트 목표, 일반 메모 보존, localized 제외, payload 검증, Interface BOM·줄바꿈, 원본 데이터 보존 및 WRLD 인덱스 제거입니다. 게임 내 검증을 대체하지 않습니다.
