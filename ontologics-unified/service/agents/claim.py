"""C claim response specialist: read-only claim trace/scope/reproduction answers."""

from service.agent_contracts import SpecialistInput
from service.claim_trace import is_claim_question
from service.errors import ServiceError
from service.gateway import ToolContext, ToolPort, ToolResult


class ClaimResponse:
    def run(self, request: SpecialistInput, port: ToolPort, context: ToolContext) -> ToolResult:
        if not is_claim_question(request.question):
            raise ServiceError("AGENT_CAPABILITY_INPUT_MISMATCH", 422)
        if request.ledger_version != context.ledger_version:
            raise ServiceError("AGENT_SNAPSHOT_CHANGED", 409)
        result = port.call("claim.trace", request.model_dump())
        if result.mutating or result.tool_name != "claim.trace" or result.snapshot != context:
            raise ServiceError("AGENT_RESULT_INVALID", 409)
        meta = result.data.get("meta", {})
        if (meta.get("company_id") != context.company_id or meta.get("snapshot_id") != context.read_snapshot_id
                or meta.get("ledger_version") != context.ledger_version
                or result.data.get("ledger_mutations", 0) != 0 or result.data.get("model_calls", 0) != 0):
            raise ServiceError("AGENT_RESULT_INVALID", 409)
        return result
