"""C claim response S3-S5: trace, scope, containment, test request/result, reproduction for A.

Boards come from the ledger fixture: B-101 arrived at the customer, B-102 is in the
warehouse; both were produced from LOT-NEW-1 (quote → PR → PO → receipt → IQC).
TEST_DATABASE_URL must be disposable.
"""
import os
from pathlib import Path
import tempfile
import unittest

from service.claim_trace import answer_claim, claim_view, is_claim_question
from service.errors import ServiceError
from service.procurement_contracts import (ClaimTestBoardResult, ClaimTestRequestContent, ClaimTestResultContent,
                                           ContainmentContent, ReproductionContent)
from tests.test_claim_documents import ClaimIntakeDocumentTests, intake_content
from tests.test_claim_projection import base_catalog


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Dedicated disposable TEST_DATABASE_URL required")
class ClaimWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.c = ClaimIntakeDocumentTests("runTest")
        self.addCleanup(self.c.doCleanups)
        self.c.setUp()
        self.p = self.c.p
        self.intake = self.p.post(intake_content(["B-101", "UNKNOWN-9"], quantity=2))

    def read(self):
        return self.p.ledger.read(self.p.author)

    def assert_code(self, code, call):
        with self.assertRaises(ServiceError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def containment(self, serials, request_type="SHIPMENT_HOLD", ref="HOLD-1"):
        return ContainmentContent(claim_intake_id=self.intake["id"], containment_ref=ref, request_type=request_type,
                                  board_serials=serials, quantity=len(serials), note="Hold boards from the same production")

    def request_test(self, serials):
        return self.p.post(ClaimTestRequestContent(claim_intake_id=self.intake["id"], test_request_ref="TR-1", board_serials=serials,
                                                   quantity=len(serials), note="Send claimed and in-scope boards to test"))

    def results(self, request, rows, ref="RES-1"):
        return self.p.post(ClaimTestResultContent(test_request_id=request["id"], test_result_ref=ref, quantity=len(rows),
                                                  results=[ClaimTestBoardResult(serial=s, outcome=o, disposition=d) for s, o, d in rows],
                                                  note="Results and dispositions returned by the test team"))

    def test_trace_goes_upstream_to_lot_inspection_and_supplier_and_scope_follows_production(self):
        claim = claim_view(self.read())["claims"][0]
        board = next(b for b in claim["claimed"] if b["serial"] == "B-101")
        self.assertEqual(board["status"], "ARRIVED")
        kinds = [step["kind"] for step in board["upstream"]["chain"]]
        self.assertEqual(kinds, ["PRODUCTION", "IQC", "RECEIPT", "PO", "PR", "QUOTE"])
        self.assertEqual(board["upstream"]["lot_code"], "LOT-NEW-1")
        self.assertIsNotNone(board["upstream"]["supplier_id"])
        self.assertEqual(claim["not_found_serials"], ["UNKNOWN-9"])
        self.assertEqual(claim["production_line"], "LINE_NOT_RECORDED")
        self.assertEqual(claim["scope_by_status"]["RECEIVED"], ["B-102"])
        self.assertEqual(claim["hold_candidates"], ["B-102"])
        self.assertEqual(claim["delivered_candidates"], ["B-101"])

    def test_containment_only_for_boards_still_holdable_and_once(self):
        self.assert_code("CONTAINMENT_OUTSIDE_SCOPE", lambda: self.p.create(self.containment(["B-101"])))
        hold = self.p.post(self.containment(["B-102"]))
        self.assertEqual(hold["content"]["resolved"]["transmission_status"], "NOT_SENT")
        self.assert_code("CONTAINMENT_ALREADY_REQUESTED", lambda: self.p.create(self.containment(["B-102"], ref="HOLD-2")))
        after = self.read()
        self.assertEqual(after["fulfillment"]["boards"]["B-102"]["status"], "RECEIVED")  # a request never moves a board

    def test_reproduction_quantity_follows_test_team_dispositions(self):
        request = self.request_test(["B-101", "B-102"])
        result = self.results(request, [("B-101", "fail", "customer_replacement")])
        summary = claim_view(self.read())["claims"][0]["reproduction_summaries"][0]
        self.assertEqual((summary["assessment_state"], summary["required_good_quantity"], summary["untested_serials"]),
                         ("lower_bound", 1, ["B-102"]))
        self.assert_code("REPRODUCTION_QUANTITY_CHANGED", lambda: self.p.create(ReproductionContent(
            test_result_id=result["id"], reproduction_ref="REP-1", quantity=2, note="Wrong quantity for A")))
        reproduction = self.p.post(ReproductionContent(test_result_id=result["id"], reproduction_ref="REP-1", quantity=1,
                                                       note="Reproduction request for A"))
        a_request = reproduction["content"]["resolved"]["a_request"]
        self.assertEqual((a_request["required_good_quantity"], a_request["transmission_status"]), (1, "NOT_SENT"))
        self.assertEqual(a_request["requested_due_date"], self.intake["content"]["requested_due_date"])
        answer = answer_claim("CLM-TEST-1 클레임 재생산 몇 대야?", self.read())
        self.assertEqual(answer["status"], "PARTIAL")  # UNKNOWN-9 is not in the ledger
        self.assertIn("재생산 필요 양품: 최소 1대", answer["answer"])
        self.assertIn("A 전달 요청서 REP-1: 양품 1대", answer["answer"])

    def test_no_demand_with_untested_boards_is_undetermined_not_zero(self):
        request = self.request_test(["B-101", "B-102"])
        result = self.results(request, [("B-101", "not_reproduced", "no_action")])
        summary = claim_view(self.read())["claims"][0]["reproduction_summaries"][0]
        self.assertEqual((summary["assessment_state"], summary["required_good_quantity"]), ("undetermined", None))
        self.assert_code("REPRODUCTION_UNDETERMINED", lambda: self.p.create(ReproductionContent(
            test_result_id=result["id"], reproduction_ref="REP-0", quantity=0, note="Nothing confirmed yet")))
        self.assert_code("TEST_RESULT_ALREADY_RECORDED", lambda: self.p.create(ClaimTestResultContent(
            test_request_id=request["id"], test_result_ref="RES-2", quantity=1,
            results=[ClaimTestBoardResult(serial="B-101", outcome="fail", disposition="customer_replacement")],
            note="Duplicate result for the same board")))

    def test_full_chain_projects_with_the_claim_extension(self):
        self.p.post(self.containment(["B-102"]))
        request = self.request_test(["B-101"])
        result = self.results(request, [("B-101", "fail", "customer_replacement")])
        self.p.post(ReproductionContent(test_result_id=result["id"], reproduction_ref="REP-1", quantity=1, note="Reproduction request for A"))
        snapshot = self.read()
        with tempfile.TemporaryDirectory() as temp:
            catalog = base_catalog(Path(temp), snapshot).with_extensions()
            from service.projections import OntologyProjector
            projection = OntologyProjector(catalog).project(snapshot, snapshot["metadata"]["server_ledger_version"], self.p.company, "INITIAL")
        self.assertEqual(projection["validation"]["state"], "CONFORMS", projection["validation"])
        types = {e["type"] for e in snapshot["entities"]}
        self.assertTrue({"ClaimIntake", "ContainmentRequest", "TestRequest", "QualityTestResult", "ReproductionRequirement"} <= types)
        predicates = {r["predicate"] for r in snapshot["relationships"]}
        self.assertTrue({"claimReportsBoard", "intake_id", "test_request_id", "test_result_ids"} <= predicates)

    def test_evidence_search_indexes_every_posted_document_including_fulfillment_and_claims(self):
        # A posted document whose node type the search index did not accept made the whole
        # corpus fail (fulfillment documents already did before the claim integration).
        from datetime import datetime, timezone
        from service.gateway import ToolContext
        from service.retrieval import _build_corpus
        self.p.post(self.containment(["B-102"]))
        request = self.request_test(["B-101"])
        result = self.results(request, [("B-101", "fail", "customer_replacement")])
        self.p.post(ReproductionContent(test_result_id=result["id"], reproduction_ref="REP-1", quantity=1, note="Reproduction request for A"))
        snapshot = self.read()
        now = datetime.now(timezone.utc)
        context = ToolContext(execution_id="probe", request_id="probe", context_revision="probe", company_id=self.p.company,
                              read_snapshot_id="probe", ledger_version=snapshot["metadata"]["server_ledger_version"],
                              as_of=now, known_as_of=now)
        corpus = _build_corpus(snapshot, context)
        posted = {d["id"]: d["kind"] for d in snapshot["procurement"]["documents"] if d["status"] == "POSTED"}
        indexed = {d["source"].get("document_id") for d in corpus.documents if d["kind"] == "development_document"}
        self.assertEqual(set(posted), indexed)
        self.assertTrue({"PRODUCTION", "SHIPMENT", "ARRIVAL", "CLAIM_INTAKE", "CONTAINMENT", "TEST_REQUEST", "TEST_RESULT",
                         "REPRODUCTION"} <= set(posted.values()))

    def test_claim_questions_are_recognized(self):
        for question in ("CLM-TEST-1 클레임 영향 범위는?", "재생산 몇 대 해야 해?", "출고 보류 대상 알려줘"):
            self.assertTrue(is_claim_question(question))
        self.assertFalse(is_claim_question("남은 68대 납기 안에 도착할 수 있어?"))
