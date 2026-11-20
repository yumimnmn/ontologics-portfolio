"""C claim response (claim_response) entry points: claim view, sample conversion, Agent read tool.

Writes go through the existing document path (/api/mks2/procurement/documents) with the
claim document kinds, so self-approval, exact-version approval, audit and outbox apply.
"""
from fastapi import Request
from pydantic import Field

from service.claim_intake import ROOT, convert_claim
from service.claim_trace import answer_claim, claim_view
from service.contracts import Contract
from service.errors import ServiceError
from service.gateway import EvidenceRef, ExecutionBudget, ToolOutput, ToolSpec

# Only the fixed synthetic samples in the repository are converted; no upload, no host parsing of user files.
SAMPLES = {"claim_mail.eml", "claim_sheet.xlsx", "claim_table.csv"}
SAMPLE_DIR = ROOT / "data/claim_response/claims"


class ClaimQuery(Contract):
    question: str = Field(min_length=1, max_length=2000)
    ledger_version: int = Field(ge=1)
    context_entity_id: str | None = Field(default=None, min_length=1, max_length=250)


class ClaimConvert(Contract):
    sample: str = Field(min_length=1, max_length=100)
    collected_at: str = Field(min_length=10, max_length=40)


def intake_draft(report):
    """ClaimIntakeContent fields from a needs_review conversion; a person still confirms them."""
    claim = report["claim"]
    return {"kind": "CLAIM_INTAKE", "claim_ref": claim["external_claim_id"], "customer_name": claim["customer_name"],
            "reported_at": claim["reported_at"], "reported_symptom": claim["reported_symptom"],
            "reported_conditions": claim.get("reported_conditions"), "requested_action": claim.get("requested_action"),
            "delivery_reference": claim.get("delivery_reference"), "requested_due_date": claim["requested_due_date"],
            "board_serials": [u["serial"] for u in report["unit_candidates"]], "quantity": report["claimed_quantity"],
            "source_format": report["format"], "source_sha256": report["sha256"], "source_locator": report["locator"],
            "provenance": "SYNTHETIC_CLAIM", "note": "고객 클레임 변환 결과를 사람이 확인함 · 불량 확정 아님"}


def mount_claim_api(app, *, ledger, gateway, principal, verified_payload, context):
    def trace_handler(actor, args, ctx):
        payload = verified_payload(actor, args.ledger_version)
        if (args.ledger_version != ctx.ledger_version or payload["metadata"]["current_ledger_version"] != args.ledger_version
                or payload["metadata"]["snapshot_id"] != ctx.read_snapshot_id):
            raise ServiceError("SNAPSHOT_CHANGED", 409)
        result = answer_claim(args.question, payload)
        result["meta"] = {"company_id": actor.company_id, "identity_revision": actor.identity_revision,
                          "snapshot_id": ctx.read_snapshot_id, "ledger_version": ctx.ledger_version,
                          "projection_version": ctx.projection_version, "ontology_version": ctx.ontology_version}
        result["execution_id"] = ctx.execution_id
        return ToolOutput(data=result, snapshot=ctx, evidence_refs=[EvidenceRef(
            evidence_id=ctx.read_snapshot_id, source_version=str(ctx.ledger_version),
            content_hash=payload["metadata"]["source_sha256"])])

    gateway.register(ToolSpec("claim.trace", "query.read", False, ClaimQuery, trace_handler))

    @app.get("/api/mks2/claims")
    def claims(request: Request):
        actor = principal(request)
        payload = ledger.read(actor)
        view = claim_view(payload)
        view["ledger_version"] = payload["metadata"]["server_ledger_version"]
        return view

    @app.post("/api/mks2/claims/query")
    def query(request: Request, body: ClaimQuery):
        # Same audited gateway path as the Agent; used by the claim tab when no model is connected.
        actor = principal(request, write=True)
        ctx = context(actor, ledger.read(actor))
        result = gateway.execute("claim.trace", body.model_dump(), principal=actor, context=ctx,
                                 budget=ExecutionBudget(ctx.execution_id, max_tool_calls=1))
        return {**result.data, "tool_name": result.tool_name, "tool_version": result.tool_version}

    @app.post("/api/mks2/claims/convert")
    def convert(request: Request, body: ClaimConvert):
        principal(request)
        if body.sample not in SAMPLES:
            raise ServiceError("CLAIM_SAMPLE_NOT_ALLOWED", 422)
        try:
            result = convert_claim(SAMPLE_DIR / body.sample, collected_at=body.collected_at)
        except ValueError as error:
            raise ServiceError(str(error).split(":")[0][:80] or "CLAIM_CONVERSION_FAILED", 422) from None
        report = result["report"]
        return {"report": report, "draft": intake_draft(report) if report["state"] == "needs_review" else None}
