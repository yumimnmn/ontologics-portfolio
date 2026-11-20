"""C claim intake on the exact-version approval path (S2); TEST_DATABASE_URL must be disposable."""
import hashlib
import os
import unittest

from service.claim_intake import ROOT, convert_claim
from service.errors import ServiceError
from service.procurement_contracts import ClaimIntakeContent, FinishedGoodsContent, ProductionContent, ShipmentContent, ArrivalContent
import tests.test_fulfillment as fulfillment_fixtures

CLAIMS = ROOT / "data/claim_response/claims"


def intake_content(serials, *, claim_ref="CLM-TEST-1", quantity=None, path=CLAIMS / "claim_table.csv"):
    report = convert_claim(path, collected_at="2026-11-20T10:00:00+09:00")["report"]
    claim = report["claim"]
    return ClaimIntakeContent(
        claim_ref=claim_ref, customer_name=claim["customer_name"], reported_at=claim["reported_at"],
        reported_symptom=claim["reported_symptom"], reported_conditions=claim.get("reported_conditions"),
        requested_action=claim.get("requested_action"), delivery_reference=claim.get("delivery_reference"),
        requested_due_date=claim["requested_due_date"], board_serials=serials,
        quantity=quantity if quantity is not None else len(serials), source_format=report["format"],
        source_sha256=report["sha256"], source_locator=report["locator"],
        note="Person confirmed the converted customer claim")


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Dedicated disposable TEST_DATABASE_URL required")
class ClaimIntakeDocumentTests(unittest.TestCase):
    def setUp(self):
        self.f = fulfillment_fixtures.FulfillmentTests("runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.p = self.f.p
        production = self.p.post(ProductionContent(iqc_id=self.f.iqc["id"], production_ref="prod-claim", board_serials=["B-101", "B-102"],
                                                   note="Two boards produced for claim tracing"))
        fg = self.p.post(FinishedGoodsContent(production_id=production["id"], receipt_ref="fg-claim", board_serials=["B-101", "B-102"],
                                              note="Two boards received to warehouse"))
        shipment = self.p.post(ShipmentContent(fg_receipt_id=fg["id"], shipment_ref="ship-claim", board_serials=["B-101"],
                                               note="One board shipped to customer"))
        self.p.post(ArrivalContent(shipment_id=shipment["id"], arrival_ref="arr-claim", board_serials=["B-101"],
                                   note="One board arrived at customer"))
        self.production_id = production["id"]

    def assert_code(self, code, call):
        with self.assertRaises(ServiceError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_confirmed_intake_links_known_boards_and_keeps_unknown_serials_open(self):
        before = self.p.ledger.read(self.p.author)
        posted = self.p.post(intake_content(["B-101", "B-102", "UNKNOWN-9"]))
        resolved = posted["content"]["resolved"]
        self.assertEqual([u["match_state"] for u in resolved["units"]], ["LINKED", "LINKED", "NOT_FOUND"])
        self.assertEqual([u["board_status"] for u in resolved["units"]], ["ARRIVED", "RECEIVED", None])
        self.assertEqual(resolved["units"][0]["production_id"], self.production_id)
        self.assertEqual(resolved["not_found_serials"], ["UNKNOWN-9"])
        self.assertFalse(resolved["confirmed_failure"])
        after = self.p.ledger.read(self.p.author)
        intake = after["claims"]["intakes"][0]
        self.assertEqual((intake["claim_ref"], intake["claimed_qty"], intake["intake_state"]), ("CLM-TEST-1", 3, "CONFIRMED"))
        # A customer report changes no board state, stock or delivery round.
        self.assertEqual(after["fulfillment"]["boards"], before["fulfillment"]["boards"])
        self.assertEqual(after["current_inventory"], before["current_inventory"])
        self.assertEqual(after["current_delivery_round"], before["current_delivery_round"])
        views = [v for v in after["events"] if v["document_kind"] == "CLAIM_INTAKE"]
        self.assertEqual(len(views), 1)
        self.assertIn("클레임 접수 기록", views[0]["summary"])

    def test_author_cannot_review_or_approve_own_claim(self):
        doc = self.p.create(intake_content(["B-101"]))
        self.assert_code("SELF_REVIEW_FORBIDDEN", lambda: self.p.action("review", doc, self.p.author))

    def test_same_claim_reference_is_recorded_once(self):
        self.p.post(intake_content(["B-101"]))
        self.assert_code("PROCUREMENT_REFERENCE_ALREADY_EXISTS", lambda: self.p.create(intake_content(["B-102"])))

    def test_contract_rejects_missing_timezone_duplicate_serials_and_bad_hash(self):
        good = intake_content(["B-101"]).model_dump()
        for change in ({"reported_at": "2026-11-12T09:30:00"}, {"board_serials": ["B-101", "B-101"]},
                       {"source_sha256": "not-a-hash"}, {"requested_due_date": "2026-11-31"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ClaimIntakeContent.model_validate({**good, **change})
        self.assertEqual(hashlib.sha256((CLAIMS / "claim_table.csv").read_bytes()).hexdigest(), good["source_sha256"])
