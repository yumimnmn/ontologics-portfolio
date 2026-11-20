# C 클레임·재생산 대응 → ontologics-chat 통합 계획

- 상태: **IMPLEMENTED_UNVERIFIED (실제 v1.7 T-Box·Neo4j·실제 모델 미실행)** · S0~S9 완료 (2026-11-20) · 합성 데이터 기준 전체 회귀 통과
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

## 3-8. S2 결과 — 클레임 접수를 원장 사건으로

chat의 업무 문서 경로(`procurement_documents` · 작성 → 다른 계정 검토·승인 → 원장 반영 · `ProcurementPosted` 사건 · Outbox)를 그대로 재사용한다. 새 테이블·새 사건 종류 없이 문서 종류만 추가했다.
- `migrations/015_claim_documents.sql`: 문서 종류에 `CLAIM_INTAKE`, `CONTAINMENT`, `TEST_REQUEST`, `TEST_RESULT`, `REPRODUCTION` 허용 (S2는 `CLAIM_INTAKE`만 사용).
- `ClaimIntakeContent`: 접수 변환 결과(클레임 번호·고객사·신고 시각(시간대 필수)·증상·희망 기한·일련번호·수량·원본 hash/위치).
- `_resolve_claim`: 일련번호를 원장의 보드(`fulfillment.boards`)에 연결. 없는 번호는 `NOT_FOUND`로 남기고 추측하지 않는다. 보드의 생산·로트·출하·도착 문서 ID를 함께 기록.
- 원장 반영: 스냅샷 `claims.intakes`에 기록. 보드 상태·재고·회차 수량은 바꾸지 않는다(고객 신고 ≠ 확인된 불량).
- 그래프: S6 전까지는 v1.7에 있는 `SourceDocument`로 투영(그래프 READY 유지).
- 사건 목록 표시: `클레임 접수 기록`.
- 테스트 `tests/test_claim_documents.py` 4개: 연결·미연결, 상태 불변, 자기검토 금지, 같은 클레임 번호 1회, 계약 검사.
- 검증: 전체 Python 549 통과(13 건너뜀) · JS 248 통과.

## 3-9. S6 결과 — 확장 T-Box·SHACL로 클레임 노드 투영

- `ontology/extensions/tbox_claim.ttl`: 팀 공통 클레임 클래스 7개·관계 5개 그대로 + `claimReportsBoard`(클레임 → 원장 보드) + 데이터 속성 6개(`claim_ref`·`customer_name`·`reported_at`·`reported_symptom`·`claimed_qty`·`confirmed_failure`).
- `ontology/extensions/shapes_claim.ttl`: 필수값, 신고 시각 오프셋 형식, 수량 ≥ 1, `confirmed_failure = false`(신고 ≠ 확인된 불량).
- `OntologyCatalog.with_extensions()`: 확장 파일을 읽어 카탈로그에 합친다(소스 목록·`ontology_version`에 반영). 공식 T-Box에 같은 이름 클래스가 있으면 확장을 적용하지 않는다. `service/main.py`·`service/__main__.py`에서 사용.
- 원장 반영: `CLAIM_INTAKE` 노드 타입을 `ClaimIntake`로 바꾸고, `LINKED` 일련번호마다 `claimReportsBoard` 관계를 만든다. `NOT_FOUND`는 관계 없이 속성에만 남는다.
- 테스트 `tests/test_claim_projection.py` 4개(가상 v1.7 기본 스키마 = chat 스냅샷이 쓰는 클래스·관계만 선언):
  - 확장 적용 시 CONFORMS · 미매핑 0 · 보드 2개 연결(모르는 번호 제외)
  - 확장 없으면 `ClaimIntake` 미매핑 → NOT_READY (확장이 필요한 이유)
  - 증상 누락 · 확인된 불량 표시 · 오프셋 없는 시각 · 수량 0 → SHACL VIOLATIONS
  - 공식 스키마에 같은 클래스가 있으면 확장 미적용
- 검증: 전체 Python 557 통과(13 건너뜀) · JS 248 통과.
- 한계: 실제 비공개 v1.7 T-Box·Neo4j로는 실행하지 않았다(NOT_RUN). 화면 그래프의 클레임 노드 색·범례는 S8.

## 3-10. S3~S5 결과 — 역추적·봉쇄·테스트·재생산

- `service/claim_trace.py`(순수 함수, 원장 스냅샷만 읽음)
  - 역추적: 보드 → 생산 실적 → 수입검사 → 입하 → 발주 → 구매 요청 → 견적(공급사). C보다 한 단계 더 깊다(공급사까지).
  - 기초 LOT으로 만든 보드는 공급사 기록이 없으므로 `NOT_RECORDED_OPENING_LOT`로 남긴다.
  - 영향 범위: 같은 생산 실적 또는 같은 LOT의 보드, 상태별(생산 완료·창고·운송·도착). 생산 라인은 원장에 없어 `LINE_NOT_RECORDED`(결정 ①).
  - 보류 후보 = 생산 완료·창고, 납품 후보 = 운송·도착. 일련번호 없는 기초 보드는 범위 안팎을 판단하지 않는다.
- 결재 문서 4종 추가(기존 작성 → 검토 → 승인 → 전기 흐름 재사용, 자기승인 금지 그대로):
  - `CONTAINMENT` 생산 중단·출고 보류: 범위 밖 보드 거부(`CONTAINMENT_OUTSIDE_SCOPE`), 같은 종류 1회.
  - `TEST_REQUEST` 테스트 의뢰: 신고·범위 보드만.
  - `TEST_RESULT` 테스트 결과: 의뢰 보드만, 보드별 결과·처리(고객 교체/재고 교체/조치 없음/판단 보류), 1회.
  - `REPRODUCTION` 재생산·A 요청서: 서버가 결과로 계산한 수량과 같아야 함(`REPRODUCTION_QUANTITY_CHANGED`), 판단 불가면 거부.
- 재생산 수량 규칙(C 6-3): 고객 교체 + 재고 교체. 결과 미정 보드가 있으면 "최소 N대", 수요 없이 미정만 있으면 "판단 불가". 창고 보드는 납품 회차에 약속돼 있어 여유 재고로 빼지 않는다(`WAREHOUSE_BOARDS_PROMISED_TO_ROUND_NOT_SUBTRACTED`) — C의 임시 운영 기록과 다른 점.
- 모든 요청서는 `transmission_status = NOT_SENT`. 보드 상태·재고·회차 수량은 바꾸지 않는다.
- 확장 SHACL: 봉쇄·테스트 의뢰 → 클레임 접수, 테스트 결과 → 테스트 의뢰, 재생산 → 테스트 결과 연결 검사.
- 테스트 `tests/test_claim_workflow.py` 6개: 역추적·공급사·범위 / 봉쇄 범위·1회 / 재생산 최소 수량·A 요청서·답변 / 판단 불가·결과 중복 / 전체 사슬 그래프 CONFORMS / 질문 인식.

## 3-11. S7 결과 — 클레임 질문 에이전트

- 읽기 전용 도구 `claim.trace`(Tool Gateway 등록, 권한 `query.read`, 변경 없음). 답변은 결정적 문장이며 숫자·일련번호는 모두 `claim_view()`에서 나온다(모델 호출 0, 원장 변경 0).
- 워크플로 라우팅: 클레임 단어(클레임·재생산·출고보류·봉쇄·테스트 의뢰 등)가 있으면 모델 해석 전에 `claim_response` 능력으로 보낸다. 다른 질문 경로는 그대로.
- 관측: `claim_response` 능력·`claim.trace` 도구 이름을 Langfuse/LangSmith 허용 목록에 추가(전송 범위는 그대로).
- API: `GET /api/mks2/claims`(클레임 화면용 읽기), `POST /api/mks2/claims/query`(모델 없는 화면에서 같은 도구 실행), `POST /api/mks2/claims/convert`(저장소의 합성 샘플 3개만 변환, 경로 입력 거부).
- 테스트 `tests/test_claim_agent.py` 4개(모델 없이 클레임 라우팅 / 다른 경로 불변 / 버전 불일치 오류 / 메일·엑셀·CSV가 같은 접수 초안), `tests/test_service_api.py`에 API 1개(읽기 전용·CSRF·샘플 제한).

## 3-12. S8 결과 — 클레임 대응 탭

- `web/mks2/claims.js` + `index.html` 탭 `클레임 대응`(`#claims`) + `styles.css` 클레임 구역. 보존 7파일은 그대로.
- 화면 구성: ① 합성 샘플 변환 → 사람이 확인 후 접수 초안 저장 ② 결재 대기 문서(작성자는 승인 버튼 없음, 다른 계정이 검토·승인 → 원장 반영) ③ 클레임별 카드: 역추적 표·영향 범위·봉쇄·테스트·재생산.
- 수량·일련번호는 화면에서 계산하지 않고 서버 값만 그린다. 서버 문자열은 모두 이스케이프.
- 클레임 문서는 공급 흐름 카드(`procurement.js`)에서 제외하고 이 탭에서만 다룬다. 활동 로그용 한국어 이름만 추가.
- 오른쪽 질의 패널 `클레임 질의`: 모델이 켜져 있으면 Agent 경로, 꺼져 있으면 `/api/mks2/claims/query`.
- 정적 파일 허용 목록(`dev/preview_server.py`)에 `claims.js` 추가.
- 테스트 `tests/test_claims_ui.mjs` 5개: 종류 목록 / 역추적·범위·이스케이프 / 작성자 승인 금지·정확 버전 검토→승인 / 출고 보류 = 서버 범위 보드·중복 비활성 / 재생산 = 서버 수량·판단 불가 시 버튼 없음.
- 미구현: 디지털 트윈의 고객사 → 출하장 역추적 애니메이션, 그래프 클레임 노드 전용 색·범례(현재 기본 색).

## 3-13. 최종 검증 (S9, 2026-11-20)

| 항목 | 결과 |
|---|---|
| Python 전체 | 572 통과 · 13 건너뜀 (S0 기준 530 → +42, 기존 테스트 실패 0) |
| JS 전체 | 253 통과 (기준 248 → +5) |
| 클레임 전용 | intake 15 · documents 4 · projection 4 · workflow 6 · agent 4 · API 1 · UI 5 |
| 실제 비공개 v1.7 T-Box · Neo4j | NOT_RUN (합성 기본 스키마 + 확장으로 검증) |
| 실제 모델 | NOT_RUN (클레임 경로는 모델을 쓰지 않음) |
| 화면 수동 확인 | NOT_RUN (서비스 실행에 비공개 입력 필요) |

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
