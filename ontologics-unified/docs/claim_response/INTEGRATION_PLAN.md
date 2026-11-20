# C 클레임·재생산 대응 → ontologics-chat 통합 계획

- 상태: **IN_PROGRESS** · S0·S1 완료 (2026-11-20)
- 작업 위치: `yumimnmn/ontologics-portfolio` · 브랜치 `feature/claim-integration` · 폴더 `ontologics-unified/`
- 기준: `ontologics-unified/` = `Ontologics-2Zo/ontologics-chat` `4448b7a` 복사본. C 원본은 `Ontologics-2Zo/ontologics` `479a45d`의 `ontologics/claim_response/`
- 원본 폴더 `ontologics-chat/`, `ontologics/`는 수정하지 않는다.

## 1. 목표

MK-S2 화면·LangGraph Agent·PostgreSQL 원장(chat)을 그대로 쓰면서, C의 업무 흐름을 같은 원장 사건과 같은 승인 경로로 추가한다.

```
클레임 접수(메일·엑셀·CSV) → 보드 일련번호 연결 → 생산·로트·출하 추적 → 보관·납품 후보 범위
→ 생산 중단·출고 보류 요청서 → 테스트 의뢰 → 테스트팀 결과·판정 → 재생산 수량 → A 전달 요청서
```

모든 요청서는 사람 검토 전 `미검토`, 승인 뒤에도 `미송부`다. 계산은 모델이 아니라 함수가 한다(C 원칙 유지).

## 2. 두 코드의 대응

| C 기능 (ontologics) | chat에 이미 있는 것 | 통합 방법 |
|---|---|---|
| `intake.py` 메일·엑셀·CSV 변환, 원본 위치(행·셀·줄) | BOM 원본 접수·격리 Runner·근거 문서 사건 `EvidenceDocumentPosted` | 파서 로직 이식. 원문 보관·hash는 chat 근거 문서 경로 재사용 |
| `ClaimIntake` 사람 확인 | 작성자 → 검토자 승인, 자기승인 금지, 정확 버전/hash | 새 원장 사건 종류 `CLAIM_INTAKE` (Domain Service + Outbox) |
| `trace.py` 일련번호 → 보드 → 생산 기록 → 라인 | 보드 일련번호 단위 생산(`PRODUCTION`: LOT/IQC)·완성품·출하·도착 사건 | chat 원장의 보드 이력으로 추적. 로트·수입검사·공급사까지 거슬러 감 (C보다 깊어짐) |
| 보관 120대·납품 후보 75대 범위 | 완성품 입고·출하·도착 상태별 보드 목록 | chat 원장에서 계산 (C의 임시 `c_operations_record` 대체) |
| `requests.py` 생산 중단·출고 보류 요청서 | 승인 카드·초안 저장·HITL | 새 사건 `CONTAINMENT_REQUEST` (미검토 → 승인 → 미송부) |
| `reproduction.py` 테스트 의뢰·결과·재생산 수량·A 요청서 | 재고·예약·부족 계산, 공급사 추천 | 새 사건 `TEST_REQUEST`, `TEST_RESULT`, `REPRODUCTION_REQUIREMENT`. 재생산 수요는 기존 소요·부족 계산에 연결 |
| `registration.py` AgentSpec `claim_response` | LangGraph Supervisor + 전문 Agent 4 + Tool Gateway | 전문 Agent 5번째 `클레임 대응` (읽기 도구만). Supervisor 라우팅에 추가 |
| `static/claims.js` 화면 | `web/mks2/` 탭 구조 | `web/mks2/claims.js` 새 탭 (MK-S2 디자인 유지) |
| 시나리오 1~4 가상 데이터 | INITIAL 원장 + 시연 회차 보드 일련번호 | chat 보드 일련번호를 쓰는 합성 클레임 데이터로 다시 작성 (`origin=synthetic`) |

## 3. 먼저 정해야 할 것 (구현 전 · 팀 규칙상 승인 필요)

### 3-1. 온톨로지(T-Box) 확장
- chat의 T-Box(클래스 52 · 관계 74 · shape 79)는 **비공개 원본**이라 공개 저장소에 없다(`PRIVATE_INPUT_ROOT`).
- 공통 기반(ontologics) T-Box에는 이미 `ClaimIntake`, `TestRequest`, `QualityTestResult`, `ReproductionRequirement`가 있다(PR #6·#7).
- 확인 필요: 비공개 v1.7 T-Box에 클레임 클래스가 이미 있는가?
  - 있으면: 매핑만 추가 (`mapping_version` 올림).
  - 없으면: 아래 7개 항목으로 확장 PR을 먼저 올리고 합의 후 진행.
  - 합의 전에는 투영에서 `UNMAPPED`로 기록만 하고 그래프 공개는 하지 않는다(화면·원장은 동작).

| PR 7개 항목 | 내용 (초안) |
|---|---|
| 업무 질문 | "이 클레임 보드들은 어느 로트·생산·출하에서 왔고, 어디까지 막아야 하나?" "재생산은 몇 대인가?" |
| 기존 구조로 안 되는 이유 | chat T-Box에 클레임·봉쇄 요청·테스트·재생산 개념이 없음 |
| 변경 전후·예시 | 4개 클래스 + 관계(클레임→보드, 의뢰→결과, 결과→재생산) 추가 · 기존 클래스 변경 없음 |
| 값 의미·원본 근거 | 공통 T-Box PR #6·#7 정의를 그대로 사용 · 원문 위치(행·셀·줄) 근거 |
| 미확인 처리 | 미연결 일련번호·수량 불일치·결과 중복은 사람 확인 · 미재현은 0이 아닌 `미정` |
| 기존 데이터·Agent 영향 | 기존 노드·관계·CQ 불변 · 새 사건만 추가 |
| 검증 결과 | SHACL CONFORMS · 기존 전체 테스트 통과 · C 시나리오 1~4 재현 |

### 3-2. 생산 라인
- C는 보드 → **생산 라인**(C-01)으로 추적하지만, chat 생산 사건에는 라인 필드가 없다(`production_ref`, LOT/IQC만).
- 선택지: ① 라인 대신 생산 실적·로트 단위로 범위 산정 (기존 계약 불변, 추천) ② 생산 사건에 선택 필드 `production_line` 추가 (계약 확장 · 승인 필요)

### 3-3. 범위
- 1단계: 접수 → 추적 → 범위 → 봉쇄 요청서 (C 1차)
- 2단계: 테스트 의뢰·결과 → 재생산 수량 → A 요청서 (C 2차) · 재생산 수요를 소요·부족 계산에 연결

## 3-4. 결정 (2026-11-19, 윰)

- **T-Box:** 비공개 v1.7 T-Box는 Git·첨부 어디에도 없어 확인 불가(Mac `PRIVATE_INPUT_ROOT`에만 있음). 팀원 확인 없이 진행한다. v1.7 파일은 건드리지 않고, 팀이 이미 승인·병합한 공통 T-Box 클레임 클래스(PR #6·#7: `ClaimIntake`, `TestRequest`, `QualityTestResult`, `ReproductionRequirement`)를 **별도 확장 파일** `ontology/tbox_claim_extension.ttl`로 둔다. chat 로더는 `tbox*.ttl`을 모두 읽으므로 v1.7과 함께 실릴 수 있다. 합칠 때 공통 담당자가 v1.7에 같은 클래스가 있으면 확장 파일을 지우고 매핑만 맞춘다.
- **생산 라인:** ① 채택. 라인 필드를 추가하지 않고 생산 실적(`production_ref`)·LOT/IQC 단위로 범위를 잡는다. 라인은 `line_not_confirmed`로 표시.
- **범위:** 2단계까지 (S0~S9 전체).

## 3-5. S0 기준선 (복사본 그대로)

| 검사 | 명령 | 결과 |
|---|---|---|
| Python | `PYTHONPATH=. TEST_DATABASE_URL=… uv run pytest -q` (로컬 PostgreSQL 16) | 530 통과 · 13 건너뜀 (Docker Runner·비공개 T-Box·Neo4j·로컬 모델 필요) |
| JS | `node --test tests/*.mjs` | 248 통과 |

## 3-6. T-Box 없이 진행하는 방식 (2026-11-20)

chat은 PostgreSQL 원장이 진실이고 RDF/Neo4j는 투영이다. 투영 payload에 T-Box에 없는 클래스가 하나라도 있으면 `UNMAPPED_CLASS` → `VIOLATIONS` → 해당 버전 전체가 NOT_READY가 된다(`service/projections.py`).
그래서 T-Box를 확인하기 전에는 **클레임 사건을 원장·API·화면·Agent에만 두고 그래프 투영 payload에는 넣지 않는다.** 기존 그래프는 계속 READY다. T-Box(또는 확장 파일)가 정해지면 S6에서 투영을 켠다.

## 3-6-1. 확장 T-Box 결정 (2026-11-20, 윰)

이 작업은 팀 레포가 아니라 개인 레포의 복제본(`ontologics-unified/`)이므로 팀 PR 합의 없이 확장 T-Box를 쓴다.
- `ontology/extensions/tbox_claim.ttl`: 팀 공통 T-Box(`Ontologics-2Zo/ontologics@479a45d` `ontology/tbox.ttl`)의 클레임 클래스 7개
  (`ClaimIntake`, `QualityCase`, `QualityScope`, `ContainmentRequest`, `TestRequest`, `QualityTestResult`, `ReproductionRequirement`)와 관계를 복사 + chat 노드(`BoardUnit`, `SourceDocument` 등)로 잇는 관계.
- `ontology/extensions/shapes_claim.ttl`: C 코드의 검사 규칙(필수값·양의 정수·시간대·근거 연결)을 SHACL로 옮김.
- 로더(`service/ontology.py`)가 v1.7과 함께 `ontology/extensions/`를 읽는다. v1.7에 같은 이름 클래스가 있으면 확장 쪽을 쓰지 않는다.
- 순서 변경: S6(투영)을 S2 바로 다음으로 당긴다 → S0·S1 → S2 → **S6** → S3 …

## 3-7. S1 결과

- `service/claim_intake.py`: C `intake.py`(Ontologics-2Zo/ontologics@479a45d) 이식. 팀 공통 모델의 `digest`·`instant`·`ROOT`만 같은 정의로 옮겼다.
- `data/claim_response/claims/`: C 가상 클레임 샘플(메일·엑셀·CSV·기대 결과) 그대로.
- `tests/test_claim_intake.py`: C `test_intake.py` 15개 이식. 팀 공통 `validate_graph` 대신 근거 연결(SourceDocument→Evidence→ClaimIntake)과 ClaimIntake 필드 계약을 검사.
- 검증: 이식 테스트 15 통과 · 전체 Python 545 통과(13 건너뜀, 기준선과 같은 이유) · JS 248 통과.

## 4. 단계별 작업 (각 단계 끝에 테스트 통과 후 커밋)

| 단계 | 내용 | 검증 |
|---|---|---|
| S0 | 기준 테스트: 복사본에서 기존 테스트가 그대로 통과하는지 확인 | 기존 node·Python 테스트 |
| S1 | `service/claim_contracts.py` 사건 계약 + `claim_intake` 파서 이식 | C `test_intake` 이식본 |
| S2 | `service/claims.py` Domain Service (원장 사건·Outbox·승인) | 자기승인 거부·멱등·버전 검사 |
| S3 | 추적·범위 계산 (chat 보드 이력) | C `test_trace` 장면 1~3·10 |
| S4 | 봉쇄 요청서 | C 장면 4 |
| S5 | 테스트 의뢰·결과·재생산·A 요청서 | C 장면 5~9 |
| S6 | 투영 매핑 (T-Box 결정에 따라) | SHACL · READY 공개 |
| S7 | 클레임 Agent + Supervisor 라우팅 + Tool Gateway 허용 도구 | Fake 모델 흐름 계약 |
| S8 | `web/mks2/claims.js` 탭 · 트윈 고객사→출하장 역추적 표시 | 화면 검사 |
| S9 | 문서·README·평가 기록 갱신 | 전체 회귀 |

## 5. 지키는 규칙
- 원본 폴더와 팀 레포 main은 건드리지 않는다. 화면 수정은 `web/mks2/`에만.
- 공통 계약(신원·승인·버전·Outbox)은 재사용만 하고 바꾸지 않는다.
- 비공개 원본(T-Box, BOM, MK-S2 원본)은 커밋하지 않는다. 가상 데이터는 `origin=synthetic`.
- 실제 모델은 승인 전 Fake로만 검증하고 실제 AI는 `NOT_RUN`으로 기록한다.
