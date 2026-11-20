# C 클레임·재생산 대응 통합 (DEC-H69)

2026-11-19~20 · 개인 복제본 `yumimnmn/ontologics-portfolio` · 브랜치 `feature/claim-integration` · 폴더 `ontologics-unified/` · 합성 데이터만 사용 · 팀 조직 레포·main 변경 없음

상태: **IMPLEMENTED_UNVERIFIED** — 합성 데이터 기준 전체 회귀 통과. 실제 비공개 v1.7 T-Box·Neo4j·실제 모델·서비스 실행 수동 확인은 NOT_RUN.

## 왜 했나

팀 최종 서비스(이 레포 `4448b7a`)에는 C 담당 기능(클레임·재생산 대응)이 없었다. C 기능은 그 이전 단계인 공통 기반 `Ontologics-2Zo/ontologics@479a45d`의 `ontologics/claim_response/`에만 있었다. 팀 프로젝트가 끝난 뒤 사용자는 최종 서비스를 개인 레포에 복제해 C 기능을 팀 규칙대로 합치기로 했다. 계획·단계별 상세는 [통합 계획](../claim_response/INTEGRATION_PLAN.md)에 있다.

## 결정

| 항목 | 결정 |
|---|---|
| 작업 위치 | 복제본 `ontologics-unified/`만 수정. 원본 폴더·팀 조직 레포는 읽기만 |
| 생산 라인 | 원장에 라인 필드가 없어 `LINE_NOT_RECORDED`(확인 불가). 범위는 생산 실적·LOT 단위 (선택지 ①) |
| 범위 | 2단계까지: 접수 → 역추적 → 영향 범위 → 생산 중단·출고 보류 → 테스트 의뢰·결과 → 재생산 수량·A 요청서 |
| T-Box | 비공개 v1.7을 쓸 수 없어 팀 공통 T-Box의 클레임 클래스 7개를 확장 파일로 둠. 공식 스키마에 같은 이름 클래스가 있으면 확장 미적용 |
| 업무 쓰기 | 새 테이블 없이 기존 구매 문서 경로 재사용 (작성 → 다른 계정 검토·승인 → 원장 반영, 정확 버전·자기승인 금지·감사·outbox) |
| 모델 | 클레임 경로는 모델을 쓰지 않음 (결정적 계산, 모델 호출 0) |

## 무엇을 바꿨나

| 영역 | 내용 |
|---|---|
| 접수 변환 | `service/claim_intake.py`: C 원본 `intake.py` 이식. 메일 .eml · 엑셀 .xlsx · CSV를 같은 접수 초안으로 변환. 합성 샘플 `data/claim_response/claims/` |
| 결재 문서 | `migrations/015_claim_documents.sql`, `service/procurement_contracts.py`: 문서 종류 `CLAIM_INTAKE`·`CONTAINMENT`·`TEST_REQUEST`·`TEST_RESULT`·`REPRODUCTION` |
| 원장 반영 | `service/procurement.py`·`procurement_state.py`: 일련번호를 원장 보드에 연결(없으면 `NOT_FOUND`), 스냅샷 `claims`에 기록. 보드 상태·재고·회차 수량 불변. 요청서 `transmission_status = NOT_SENT` |
| 역추적·범위 | `service/claim_trace.py`(순수 함수): 보드 → 생산 실적 → 수입검사 → 입하 → 발주 → 구매 요청 → 견적(공급사). 같은 생산·LOT 범위, 보류 후보(생산 완료·창고)·납품 후보(운송·도착). 기초 LOT은 `NOT_RECORDED_OPENING_LOT` |
| 재생산 수량 | 고객 교체 + 재고 교체. 결과 미정 보드가 있으면 최소 수량(`lower_bound`), 미정만 있으면 판단 불가(`undetermined`). 창고 보드는 납품 회차에 약속돼 있어 여유 재고로 빼지 않음 |
| 온톨로지 | `ontology/extensions/tbox_claim.ttl`·`shapes_claim.ttl`, `OntologyCatalog.with_extensions()`. `ClaimIntake` 등 7클래스, `claimReportsBoard`, 상위 문서 연결 SHACL |
| Agent | `service/agents/claim.py`, `service/agent_workflow.py`: 5번째 전문 Agent `claim_response`. 클레임 단어가 있으면 분류 단계에서 바로 연결. 읽기 도구 `claim.trace`(`query.read`, 변경 없음). 관측 이름 허용 목록 추가 |
| API | `service/claim_api.py`: `GET /api/mks2/claims`, `POST /api/mks2/claims/query`(같은 도구, 모델 없는 화면용), `POST /api/mks2/claims/convert`(저장소 합성 샘플 3개만) |
| 화면 | `web/mks2/claims.js`, `index.html`, `app.js`, `styles.css`: `클레임 대응` 탭과 `클레임 질의` 패널. 작성자에게는 승인 버튼 없음. 클레임 문서는 공급 흐름 카드(`procurement.js`)에서 제외. 정적 허용 목록(`dev/preview_server.py`)에 `claims.js` |

## 검증

| 검사 | 명령 | 결과 |
|---|---|---|
| Python 전체 | `PYTHONPATH=. TEST_DATABASE_URL=… uv run pytest -q` (로컬 PostgreSQL 16) | 572 통과 · 13 건너뜀 (기준선 530, 기존 테스트 실패 0) |
| JS 전체 | `node --test tests/*.mjs` | 253 통과 (기준선 248) |
| 클레임 전용 | `tests/test_claim_*.py`, `tests/test_claims_ui.mjs`, `tests/test_service_api.py` 클레임 1건 | 접수 15 · 문서 4 · 투영 4 · 흐름 6 · Agent 4 · API 1 · 화면 5 |
| 화면 렌더 | 합성 데이터 미리보기 (Playwright) | 콘솔 오류 0 |

건너뜀 13건은 기준선과 같은 이유(Docker Runner·비공개 T-Box·Neo4j·로컬 모델 필요)다.

## 하지 않은 것

- 실제 비공개 v1.7 T-Box·Neo4j로 투영·SHACL 실행 (NOT_RUN)
- 실제 모델 호출 (클레임 경로는 모델을 쓰지 않음)
- 서비스를 띄운 수동 화면 확인 (비공개 입력 필요)
- 디지털 트윈 역추적 표시, 그래프 클레임 노드 전용 색·범례
- 팀 조직 레포 PR·push, 개인 레포 main 병합
