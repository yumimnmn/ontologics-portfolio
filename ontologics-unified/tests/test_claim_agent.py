"""C claim specialist (S7): claim questions route deterministically to claim.trace, read-only.

Uses the synthetic agent host from tests/test_agent_workflow.py plus a synthetic claim.trace
tool. TEST_DATABASE_URL must be disposable.
"""
import os
import unittest

from service.gateway import ToolOutput, ToolSpec
from service.claim_api import ClaimQuery
import tests.test_agent_workflow as agent_fixtures


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL not configured")
class ClaimAgentTests(unittest.TestCase):
    def setUp(self):
        self.a = agent_fixtures.AgentWorkflowTests("run")
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.calls, self.model = [], []
        self.host, _ = agent_fixtures.build_host(self.a.db, route_model=lambda *args: self.model.append(args))

        def trace(principal, arguments, ctx):
            self.calls.append(arguments.question)
            return ToolOutput(snapshot=ctx, data={"status": "ANSWERED", "intent": "claim", "answer": "합성 클레임 답변",
                "model_calls": 0, "ledger_mutations": 0, "evidence_ids": [],
                "meta": {"company_id": ctx.company_id, "snapshot_id": ctx.read_snapshot_id,
                         "ledger_version": ctx.ledger_version, "projection_version": ctx.projection_version}})
        self.host.gateway.register(ToolSpec("claim.trace", "query.read", False, ClaimQuery, trace))
        self.host.setup()

    def run_question(self, question, capability=None):
        created = self.host.create(self.a.actor, self.a.request(question, capability))
        return self.host.run(self.a.actor, created["execution_id"])

    def test_claim_question_routes_to_claim_specialist_without_model_routing(self):
        result = self.run_question("CLM-TEST-1 클레임 영향 범위와 재생산 수량은?")
        self.assertEqual(result["status"], "COMPLETED", result["error_code"])
        self.assertEqual((result["capability"], result["tool_calls"], result["ledger_mutations"]), ("claim_response", 1, 0))
        self.assertEqual(result["result"]["answer"], "합성 클레임 답변")
        self.assertEqual(self.model, [])
        self.assertEqual(len(self.calls), 1)

    def test_other_questions_keep_their_existing_route(self):
        result = self.run_question("납품 현황", "fulfillment_read")
        self.assertEqual(result["capability"], "fulfillment_read")
        self.assertEqual(self.calls, [])

    def test_claim_specialist_rejects_a_non_claim_question(self):
        result = self.run_question("납품 현황", "claim_response")
        self.assertEqual(result["error_code"], "AGENT_CAPABILITY_INPUT_MISMATCH")


class ClaimSampleDraftTests(unittest.TestCase):
    def test_each_sample_converts_to_a_valid_intake_draft(self):
        from service.claim_api import SAMPLE_DIR, SAMPLES, intake_draft
        from service.claim_intake import convert_claim
        from service.procurement_contracts import ClaimIntakeContent
        drafts = []
        for name in sorted(SAMPLES):
            report = convert_claim(SAMPLE_DIR / name, collected_at="2026-11-20T10:00:00+09:00")["report"]
            draft = ClaimIntakeContent.model_validate(intake_draft(report))
            drafts.append((draft.claim_ref, draft.customer_name, tuple(draft.board_serials), draft.quantity))
        self.assertEqual(len(set(drafts)), 1)  # mail, Excel and CSV describe the same claim
