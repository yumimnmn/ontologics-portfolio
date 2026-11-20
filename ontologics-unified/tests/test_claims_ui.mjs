import assert from 'node:assert/strict';
import test from 'node:test';

// The claim tab with an in-process fake server: no service, no model, no ledger.
class Root {
  constructor() { this.innerHTML = ''; this.listeners = {}; this.className = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  remove() { this.removed = true; }
}
globalThis.document = { createElement: () => new Root() };
const { mountClaims, CLAIM_KINDS } = await import('../web/mks2/claims.js');
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function claimView(overrides = {}) {
  return { claim_ref: 'CLM-<1>', intake_document_id: 'doc-intake', customer_name: '합성 고객', reported_symptom: '부팅 실패',
    claimed_qty: 2, requested_due_date: '2026-12-01',
    claimed: [
      { serial: 'B-101', match_state: 'LINKED', status: 'ARRIVED', status_label: '고객 도착', lot_code: 'LOT-1',
        upstream: { supplier_id: 'SUP-1', chain: [{ kind: 'PRODUCTION', production_ref: 'PRD-1' }, { kind: 'QUOTE', quote_ref: 'Q-1' }] } },
      { serial: 'B-999', match_state: 'NOT_FOUND', status: null, status_label: '원장에 없음 · 사람 확인 필요' }],
    not_found_serials: ['B-999'],
    scope_by_status: { PRODUCED: [], RECEIVED: ['B-102', 'B-103'], SHIPPED: [], ARRIVED: ['B-101'] },
    untraceable_opening_boards: null, containments: [], test_requests: [], test_results: [], reproduction_summaries: [], reproductions: [],
    ...overrides };
}
function harness({ view, documents = [], actor = 'actor-b', permissions = ['document.create', 'document.approve', 'document.post'] }) {
  const requests = [];
  const api = async (path, body) => {
    requests.push({ path, body });
    if (path === '/api/mks2/claims') return { claims: [view], ledger_version: 9 };
    if (path === '/api/mks2/procurement/documents' && body === undefined) return { documents };
    if (path.endsWith('/review')) return { ...documents[0], status: 'REVIEWED', version: 2, payload_hash: 'h2' };
    return { id: 'doc-new', status: 'DRAFT' };
  };
  const container = { replaceChildren(node) { this.root = node; } };
  const posted = [];
  const instance = mountClaims(container, { snapshot: { meta: { ledger_version: 9 } }, api,
    getIdentity: () => ({ actor_id: actor, permitted_actions: permissions }), onPosted: value => posted.push(value) });
  const root = container.root;
  const click = dataset => root.listeners.click({ target: { closest: () => ({ dataset, disabled: false }) } });
  return { root, requests, click, posted, instance };
}

test('claim kinds are the five C document kinds', () => {
  assert.deepEqual([...CLAIM_KINDS], ['CLAIM_INTAKE', 'CONTAINMENT', 'TEST_REQUEST', 'TEST_RESULT', 'REPRODUCTION']);
});

test('trace, scope and missing serials come from the server view and are escaped', async () => {
  const { root } = harness({ view: claimView() });
  await settle();
  assert.match(root.innerHTML, /CLM-&lt;1&gt;/);
  assert.doesNotMatch(root.innerHTML, /CLM-<1>/);
  assert.match(root.innerHTML, /불량 확정 아님/);
  assert.match(root.innerHTML, /PRD-1<\/span><span class="arrow">←<\/span><span class="step">Q-1/);
  assert.match(root.innerHTML, /창고 보관 2대/);
  assert.match(root.innerHTML, /원장에 없는 번호: B-999/);
  assert.match(root.innerHTML, /생산 라인은 원장에 기록되지 않아 확인 불가/);
});

test('the author of a draft cannot approve it; another account reviews then approves the exact version', async () => {
  const draft = { id: 'doc-1', kind: 'CONTAINMENT', status: 'DRAFT', version: 1, payload_hash: 'h1', created_by: 'actor-a' };
  const own = harness({ view: claimView(), documents: [draft], actor: 'actor-a' });
  await settle();
  assert.match(own.root.innerHTML, /다른 계정의 검토·승인 대기/);
  assert.doesNotMatch(own.root.innerHTML, /data-act="approve"/);
  const other = harness({ view: claimView(), documents: [draft], actor: 'actor-b' });
  await settle();
  other.click({ act: 'approve', doc: 'doc-1' });
  await settle(); await settle();
  const actions = other.requests.filter(r => r.body && r.path.includes('/documents/doc-1/'));
  assert.deepEqual(actions.map(r => r.path.split('/').pop()), ['review', 'approve']);
  assert.equal(actions[0].body.expected_version, 1);
  assert.equal(actions[1].body.expected_version, 2);
  assert.equal(actions[1].body.payload_hash, 'h2');
});

test('shipment hold uses the server scope boards; an existing request disables it', async () => {
  const { requests, click } = harness({ view: claimView() });
  await settle();
  click({ act: 'contain', type: 'SHIPMENT_HOLD', claim: 'doc-intake' });
  await settle(); await settle();
  const create = requests.find(r => r.path === '/api/mks2/procurement/documents' && r.body);
  assert.equal(create.body.expected_ledger_version, 9);
  assert.deepEqual(create.body.content, { kind: 'CONTAINMENT', claim_intake_id: 'doc-intake', containment_ref: 'CLM-<1>-HOLD',
    request_type: 'SHIPMENT_HOLD', board_serials: ['B-102', 'B-103'], quantity: 2, note: '역추적 범위 기반 내부 요청 · 미송부' });
  const held = harness({ view: claimView({ containments: [{ request_type: 'SHIPMENT_HOLD', containment_ref: 'X', quantity: 2 }] }) });
  await settle();
  assert.match(held.root.innerHTML, /data-type="SHIPMENT_HOLD" data-claim="doc-intake" disabled/);
  assert.match(held.root.innerHTML, /data-type="PRODUCTION_STOP" data-claim="doc-intake" disabled/); // no PRODUCED boards
});

test('reproduction request carries the server-calculated quantity; undetermined offers no request', async () => {
  const summary = { test_request_id: 'doc-tr', assessment_state: 'lower_bound', required_good_quantity: 1,
    customer_replacement_quantity: 1, stock_replacement_quantity: 0, unresolved_quantity: 1 };
  const view = claimView({ test_requests: [{ document_id: 'doc-tr', test_request_ref: 'TR', board_serials: ['B-101', 'B-102'] }],
    test_results: [{ document_id: 'doc-res', test_request_id: 'doc-tr' }], reproduction_summaries: [summary] });
  const { root, requests, click } = harness({ view });
  await settle();
  assert.match(root.innerHTML, /재생산 필요 양품 최소 <b>1대<\/b>/);
  click({ act: 'reproduce', result: 'doc-res', qty: '1', claimRef: 'CLM-1' });
  await settle(); await settle();
  const create = requests.find(r => r.body?.content?.kind === 'REPRODUCTION');
  assert.equal(create.body.content.quantity, 1);
  assert.equal(create.body.content.test_result_id, 'doc-res');
  const undetermined = harness({ view: { ...view, reproduction_summaries: [{ ...summary, assessment_state: 'undetermined', required_good_quantity: null }] } });
  await settle();
  assert.match(undetermined.root.innerHTML, /판단 불가/);
  assert.doesNotMatch(undetermined.root.innerHTML, /data-act="reproduce"/);
});
