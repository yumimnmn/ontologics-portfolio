"""C claim response (claim_response) reads over the ledger snapshot: trace, scope, reproduction.

Pure functions. Every fact comes from posted ledger records in the snapshot
(`claims`, `fulfillment.boards`, `procurement.documents`). Nothing is guessed:
a serial the ledger does not hold stays NOT_FOUND, opening-balance boards
without serials stay UNKNOWN, and the production line is not recorded in the
chat ledger, so it is reported as LINE_NOT_RECORDED (decision 2026-11-19, option 1).
"""
from __future__ import annotations

STATUS_LABELS = {"PRODUCED": "생산 완료 · 입고 전", "RECEIVED": "창고 보관", "SHIPPED": "운송 중", "ARRIVED": "고객 도착"}
# Boards not yet with the customer can still be held; shipped ones are delivery candidates.
HOLDABLE = ("PRODUCED", "RECEIVED")
DELIVERED = ("SHIPPED", "ARRIVED")
CONFIRMED, LOWER_BOUND, UNDETERMINED = "confirmed", "lower_bound", "undetermined"


def _documents(payload):
    return {row["id"]: row for row in (payload.get("procurement") or {}).get("documents", [])}


def _claims(payload):
    return payload.get("claims") or {}


def upstream(payload, production_id):
    """Production → IQC → receipt → order → request → quote (supplier), as posted."""
    documents = _documents(payload)
    chain, current = [], documents.get(production_id)
    while current is not None:
        resolved = current["content"].get("resolved", {})
        step = {"kind": current["kind"], "document_id": current["id"], "ledger_version": current["ledger_version"]}
        for key in ("production_ref", "inspection_ref", "receipt_ref", "quote_ref", "lot_code"):
            if current["content"].get(key):
                step[key] = current["content"][key]
        for key in ("lot_code", "item_id", "supplier_id"):
            if resolved.get(key):
                step[key] = resolved[key]
        chain.append(step)
        parent = resolved.get("parent", {}).get("id")
        if current["kind"] == "PR" and current["content"].get("quote_id"):
            parent = current["content"]["quote_id"]
        current = documents.get(parent) if parent else None
    supplier = next((s.get("supplier_id") for s in chain if s.get("supplier_id")), None)
    lot = next((s.get("lot_code") for s in chain if s.get("lot_code")), None)
    iqc = next((s for s in chain if s["kind"] == "IQC"), None)
    return {"chain": chain, "lot_code": lot, "supplier_id": supplier,
            "inspection_document_id": iqc["document_id"] if iqc else None,
            # A production from an opening-balance LOT has no posted receipt/IQC/supplier chain.
            "supplier_state": "RECORDED" if supplier else "NOT_RECORDED_OPENING_LOT"}


def intake_by_document(payload, intake_document_id):
    return next((x for x in _claims(payload).get("intakes", []) if x["document_id"] == intake_document_id), None)


def trace_intake(payload, intake):
    """Claimed boards → current state and upstream records; scope = same production or LOT."""
    boards = (payload.get("fulfillment") or {}).get("boards", {})
    linked = [u for u in intake["units"] if u["match_state"] == "LINKED"]
    claimed = []
    for unit in intake["units"]:
        board = boards.get(unit["serial"])
        entry = {"serial": unit["serial"], "match_state": unit["match_state"],
                 "status": board.get("status") if board else None,
                 "status_label": STATUS_LABELS.get(board.get("status")) if board else "원장에 없음 · 사람 확인 필요"}
        if board:
            entry.update(production_id=board.get("production_id"), lot_code=board.get("lot_code"),
                         upstream=upstream(payload, board.get("production_id")))
        claimed.append(entry)
    production_ids = sorted({boards[u["serial"]]["production_id"] for u in linked if u["serial"] in boards})
    lot_codes = sorted({boards[u["serial"]]["lot_code"] for u in linked if u["serial"] in boards and boards[u["serial"]].get("lot_code")})
    claimed_serials = {u["serial"] for u in intake["units"]}
    scope = []
    for serial, board in sorted(boards.items()):
        reasons = []
        if board.get("production_id") in production_ids:
            reasons.append("same_production")
        if board.get("lot_code") in lot_codes:
            reasons.append("same_lot")
        if reasons:
            scope.append({"serial": serial, "status": board.get("status"), "status_label": STATUS_LABELS.get(board.get("status")),
                          "reasons": reasons, "claimed": serial in claimed_serials})
    by_status = {status: [row["serial"] for row in scope if row["status"] == status] for status in STATUS_LABELS}
    legacy = (payload.get("fulfillment") or {}).get("legacy") or {}
    return {"claim_ref": intake["claim_ref"], "intake_document_id": intake["document_id"], "customer_name": intake["customer_name"],
            "reported_symptom": intake["reported_symptom"], "claimed_qty": intake["claimed_qty"],
            "claimed": claimed, "not_found_serials": [u["serial"] for u in intake["units"] if u["match_state"] == "NOT_FOUND"],
            "production_ids": production_ids, "lot_codes": lot_codes,
            "production_line": "LINE_NOT_RECORDED",
            "scope": scope, "scope_by_status": by_status,
            "hold_candidates": [row["serial"] for row in scope if row["status"] in HOLDABLE],
            "delivered_candidates": [row["serial"] for row in scope if row["status"] in DELIVERED],
            # Opening-balance boards have no serials, so they cannot be placed in or out of scope.
            "untraceable_opening_boards": {k: v for k, v in legacy.items() if v} or None,
            "confirmed_failure": False}


def reproduction_summary(payload, test_request_document_id):
    """C 6-3 rule over posted results: count boards the test team dispositioned for replacement.

    customer = customer_replacement, stock = stock_replacement, unresolved = requested boards
    without a result + results marked unresolved. Warehouse boards are promised to the current
    delivery round, so (unlike C's temporary operations record) none is subtracted as spare stock.
    - no unresolved boards           -> confirmed
    - unresolved boards, some demand -> lower_bound (the final number may grow)
    - unresolved boards, no demand   -> undetermined (no quantity: 0 would read as nothing to make)
    """
    claims = _claims(payload)
    request = next((x for x in claims.get("test_requests", []) if x["document_id"] == test_request_document_id), None)
    if request is None:
        return None
    results = {}
    for posted in claims.get("test_results", []):
        if posted["test_request_id"] == test_request_document_id:
            for row in posted["results"]:
                results[row["serial"]] = row
    customer = sorted(s for s, r in results.items() if r["disposition"] == "customer_replacement")
    stock = sorted(s for s, r in results.items() if r["disposition"] == "stock_replacement")
    untested = sorted(s for s in request["board_serials"] if s not in results)
    unresolved = len(untested) + sum(r["disposition"] == "unresolved" for r in results.values())
    demand = len(customer) + len(stock)
    state = UNDETERMINED if unresolved and not demand else LOWER_BOUND if unresolved else CONFIRMED
    return {"test_request_id": test_request_document_id, "customer_replacement_serials": customer,
            "stock_replacement_serials": stock, "untested_serials": untested,
            "customer_replacement_quantity": len(customer), "stock_replacement_quantity": len(stock),
            "unresolved_quantity": unresolved, "assessment_state": state,
            "required_good_quantity": None if state == UNDETERMINED else demand,
            "spare_stock_rule": "WAREHOUSE_BOARDS_PROMISED_TO_ROUND_NOT_SUBTRACTED"}


def claim_view(payload):
    """Everything the claim tab and the claim Agent read, per confirmed intake."""
    claims = _claims(payload)
    view = []
    for intake in claims.get("intakes", []):
        trace = trace_intake(payload, intake)
        requests = [x for x in claims.get("test_requests", []) if x["intake_document_id"] == intake["document_id"]]
        request_ids = {x["document_id"] for x in requests}
        results = [x for x in claims.get("test_results", []) if x["test_request_id"] in request_ids]
        result_ids = {x["document_id"] for x in results}
        view.append({**trace, "requested_due_date": intake["requested_due_date"], "intake_ledger_version": intake["ledger_version"],
                     "containments": [x for x in claims.get("containments", []) if x["intake_document_id"] == intake["document_id"]],
                     "test_requests": requests, "test_results": results,
                     "reproduction_summaries": [reproduction_summary(payload, x["document_id"]) for x in requests],
                     "reproductions": [x for x in claims.get("reproductions", []) if x["test_result_id"] in result_ids]})
    return {"claims": view, "scope": "INTERNAL_DEVELOPMENT_ONLY", "model_calls": 0, "ledger_mutations": 0}


CLAIM_WORDS = ("클레임", "불량신고", "재생산", "출고보류", "생산중단", "봉쇄", "테스트의뢰", "테스트결과", "영향범위", "claim")


def is_claim_question(question: str) -> bool:
    compact = "".join(question.split()).casefold()
    return any(word in compact for word in CLAIM_WORDS)


def answer_claim(question: str, payload: dict) -> dict:
    """Deterministic claim answer: numbers and serials come only from claim_view()."""
    view = claim_view(payload)["claims"]
    compact = "".join(question.split()).casefold()
    if not view:
        return {"status": "UNKNOWN", "intent": "claim", "answer": "원장에 반영된 클레임 접수가 없습니다. 클레임 대응 탭에서 접수를 등록·승인해 주세요.",
                "claims": [], "model_calls": 0, "ledger_mutations": 0}
    named = [c for c in view if c["claim_ref"].casefold() in compact]
    if len(view) > 1 and not named:
        return {"status": "NEEDS_CLARIFICATION", "intent": "claim",
                "answer": "어느 클레임인지 클레임 번호로 지정해 주세요: " + ", ".join(c["claim_ref"] for c in view),
                "claims": [c["claim_ref"] for c in view], "model_calls": 0, "ledger_mutations": 0}
    claim = (named or view)[0]
    lines = [f"{claim['customer_name']} 클레임 {claim['claim_ref']} · 신고 {claim['claimed_qty']}대 · 증상: {claim['reported_symptom']} (신고 내용이며 불량 확정 아님)"]
    linked = [c for c in claim["claimed"] if c["match_state"] == "LINKED"]
    lines.append(f"원장 보드 연결 {len(linked)}대" + (f" · 원장에 없는 번호 {', '.join(claim['not_found_serials'])}는 사람 확인 필요" if claim["not_found_serials"] else ""))
    for board in linked:
        up = board.get("upstream") or {}
        supplier = up.get("supplier_id") or "공급사 기록 없음(기초 LOT)"
        lines.append(f"· {board['serial']}: {board['status_label']} ← 생산 실적 ← LOT {board.get('lot_code') or '미기록'} ← {supplier}")
    by = claim["scope_by_status"]
    lines.append("영향 후보(같은 생산 실적·LOT): " + " · ".join(f"{STATUS_LABELS[s]} {len(by[s])}대" for s in STATUS_LABELS if by[s]) +
                 " · 생산 라인은 원장에 기록되지 않아 확인 불가")
    if claim["untraceable_opening_boards"]:
        lines.append("기초 보드(일련번호 없음)는 범위 안팎을 판단할 수 없습니다.")
    for c in claim["containments"]:
        lines.append(f"봉쇄 요청 {c['containment_ref']}: {dict(PRODUCTION_STOP='생산 중단', SHIPMENT_HOLD='출고 보류')[c['request_type']]} {c['quantity']}대 · 미송부")
    for summary in claim["reproduction_summaries"]:
        if summary is None:
            continue
        if summary["assessment_state"] == UNDETERMINED:
            lines.append(f"재생산 수량: 판단 불가 · 결과 미정 {summary['unresolved_quantity']}대")
        else:
            label = "최소 " if summary["assessment_state"] == LOWER_BOUND else ""
            lines.append(f"재생산 필요 양품: {label}{summary['required_good_quantity']}대 (고객 교체 {summary['customer_replacement_quantity']} · 재고 교체 {summary['stock_replacement_quantity']}"
                         + (f" · 결과 미정 {summary['unresolved_quantity']}" if summary["unresolved_quantity"] else "") + ")")
    for r in claim["reproductions"]:
        lines.append(f"A 전달 요청서 {r['reproduction_ref']}: 양품 {r['required_good_quantity']}대 · 희망 기한 {r['requested_due_date']} · 미송부")
    status = "PARTIAL" if claim["not_found_serials"] or claim["untraceable_opening_boards"] else "ANSWERED"
    return {"status": status, "intent": "claim", "answer": "\n".join(lines), "claim": claim,
            "evidence_ids": sorted({claim["intake_document_id"], *(c["document_id"] for c in claim["containments"]),
                                    *(c["document_id"] for c in claim["test_requests"]), *(c["document_id"] for c in claim["test_results"]),
                                    *(c["document_id"] for c in claim["reproductions"])}),
            "model_calls": 0, "ledger_mutations": 0}
