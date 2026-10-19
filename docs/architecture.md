# TMR Korean Patcher Architecture

## 1. 출력 구조

패쳐는 실행 중 사용자의 기존 MO2 모드 파일을 직접 수정하지 않는다. 먼저 별도의 `Output` 트리를 만든다.

### 본편 번역

본편/공식 DLC 한국어 리소스는 다음 새 MO2 모드로 생성한다.

`Output/mods/FO4 KOREAN/`

사용자는 Output을 TMR MO2 루트에 복사한 뒤 MO2에서 `FO4 KOREAN`을 체크한다.

### TMR 모드 번역

각 번역 파일은 현재 승자(winner)를 제공하는 원본 MO2 모드의 **폴더명과 Data 상대경로**를 그대로 재현한다.

예:

`Output/mods/Previsibines Repair Pack - Full (1.11.191)/prp.esp`

`Output/mods/Complex Vendors/MCM/Config/Complex Vendors/config.json`

`Output/mods/Mod Configuration Menu 1.11.221/Interface/Translations/MCM_en.txt`

사용자가 Output을 TMR MO2 루트에 복사하면 기존 원본 모드 폴더에 번역 파일이 병합/덮어쓰기된다.

MO2 overwrite가 실제 provider인 파일은 `Output/overwrite/`를 사용한다.

## 2. 제외 플러그인

다음 플러그인은 런타임과 릴리즈 데이터 생성 단계 모두에서 명시적으로 제외한다.

- `ptrfo4001_t60pistol.esl`
- `ptrfo4002_vangraff.esl`

direct map 및 번역 결과를 생성하지 않는다.

## 3. 플러그인 적용 전략

### 설치 원본에 번역 데이터 적용

배포물에는 완성된 ESP/ESM/ESL이나 원작 모드 아카이브를 포함하지 않는다.
원본 해시가 같더라도 미리 번역된 플러그인을 복사하지 않는다.
`TmrPluginTranslator`는 사용자가 설치한 현재 파일을 읽고 번역 사전을 적용한다.
이전 catalog의 payload 참조도 사용하지 않는다.

업데이트로 추가된 레코드·헤더·비번역 데이터는 현재 설치본에서 보존한다.
현재 표시 원문과 일치하지 않는 사전 문구는 번역하지 않는다.
완성된 플러그인은 사용자 컴퓨터의 Output 또는 개발용 검증 폴더에서만 생성한다.

우선순위:

1. 모드 전용 direct SST 매핑
2. Fallout4.esm + 공식 DLC 번역 상속

본편/DLC 상속은 owner/FormID/현재 영문 원문을 기준으로 하며, QUST/TERM처럼 같은 필드가 반복되는 레코드는 xTranslator의 REC:FIELD + rec_id 의미를 보존해 적용한다.

## 4. 본편/DLC fallback bank

개발 단계에서 다음 사전을 하나의 fallback bank로 생성한다.

- Fallout4.esm
- DLCRobot.esm
- DLCWorkshop01.esm
- DLCCoast.esm
- DLCWorkshop02.esm
- DLCWorkshop03.esm
- DLCNukaWorld.esm

SSU8 구형 SST는 마스터 인덱스를 공식 마스터 순서로 복원한다.

## 5. MCM / Interface

MCM과 Interface 번역도 각 원본 MO2 provider 폴더와 동일한 경로에 출력한다.

SimpleMcmJsonTranslator의 로컬 DB는 개발 단계에서 JSON 매핑으로 변환한다. 릴리즈 런타임은 BinaryFormatter DB를 읽지 않는다.

Custom TXT SST는 릴리즈 준비 단계에서 source → Korean JSON으로 변환한다.

## 6. 내장 본편 한국어 리소스

v1.0.1부터 `FO4_AE_1.11.191.Kor`를 릴리즈 ZIP에 포함한다.

패쳐는 실행 파일 옆의 이 폴더를 자동으로 읽고 `Output/mods/FO4 KOREAN`으로 복사한다.

복사 대상:

- `Interface`
- `Programs`
- `Strings`

영문판 런타임 호환을 위해 원래 `_en` 파일명을 유지한다.

## 7. 저장 검증

번역 정책 버전 6은 원본 바이트 보존 문자열 치환, UTF-8 저장/재읽기, 지몬자 번역 제외 및 WRLD 인덱스 제거를 포함한다.
모든 플러그인에 같은 저장 검증을 적용하며, 현재 설치 원본과 사전으로 결과를 생성한다.
카탈로그의 과거 원본 해시는 참고 정보이며 완성 파일 복사를 허용하지 않는다.

Mutagen의 원문/번역 비교용 사본에서 승인된 문자열 변경을 찾고 OriginalTextWriter가
그 변경만 원본 레코드에 치환한다. 비표시 필드, 원본 헤더와 필드 순서는 유지한다.
문자열 전체와 필드별 발생 순서까지 대응되지 않으면 출력을 거부한다.
그 후 WorldIndexStripper가 WRLD의 OFST·CLSZ와 해당 XXXX를 제거한다.
이는 xTranslator 1.7.3의 임시 대응을 따르며 셀 오프셋 재계산을 대체한다.
압축 WRLD는 해제·필터링·재압축하고 레코드 및 상위 그룹 크기를 갱신한다.
다른 필드 및 그 필드의 XXXX는 보존한다. TES4 인덱스는 처리하지 않는다.
소스 프리플라이트는 구조를 검사하며 유효한 WRLD 인덱스는 허용한다.
손상된 경계나 TES4 인덱스는 실패/제외한다.
번역할 내용이 없으면 저장하지 않는다. 인덱스 제거 실패 시 생성한 파일을 삭제한다.
파일 검증과 게임 내 안정성·성능 검증은 별개다.

번역 백엔드는 플러그인 저장 후 다시 읽어 다음을 확인한다.

- 레코드 FormKey 집합/개수
- 마스터 목록 및 순서
- 출력 파일 재파싱 가능 여부

## 8. 배포

릴리즈 ZIP은 다음을 포함한다.

- `TMR-Korean-Patcher.exe`
- `FO4_AE_1.11.191.Kor/`
- `TranslationData/catalog.json`
- direct mappings
- base/DLC fallback bank
- self-contained `TmrPluginTranslator.exe`
- MCM/Interface JSON mappings
- LICENSE / THIRD_PARTY_NOTICES

원작 플러그인과 완성된 번역 플러그인은 소스 저장소와 릴리즈에 포함하지 않는다.
원작 모드 설치는 사용자가 별도로 완료해야 한다.

Python, .NET Runtime, xTranslator 설치는 릴리즈 사용자에게 요구하지 않는다.


## 9. 최종 저장 검증 (v1.0.4)

FinalPluginVerifier는 문자열 치환과 WorldIndexStripper 처리 이후의 실제 출력 전체를 원본과 대조한다. 원본과 그룹 중첩·순서·레코드 식별자·비길이 헤더가 같아야 하며, 사전 문자열 쌍과 WRLD의 OFST/CLSZ 제거 외에는 원시 필드 바이트 변경을 거부한다. 지몬자 보호 레코드는 전체 원시 바이트를 비교한다. 실패 시 출력 플러그인을 폐기한다. 모든 생성 결과에 정책 6, final_binary_verified 및 strip_wrld_ofst_clsz_v1 정책 식별자를 요구한다.

인덱스 삭제의 근거는 xTranslator 1.7.3 제작자의 변경 기록이다. 공식 공개 소스는 1.6.0으로 최신 구현의 직접 검토와 구분한다. 상세 내용은 validation/xtranslator-prp-review.md를 참고한다.
