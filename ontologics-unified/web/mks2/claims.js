// C 클레임 대응 탭 (claim_response). Every serial, status and quantity shown here comes from the
// server (GET /api/mks2/claims, which reads posted ledger records). Writes are claim documents on
// the existing document path: draft → review → approve → post, with author ≠ approver enforced by
// the server. Nothing is sent to a customer, production, logistics or A (전송 상태 미송부).
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const CLAIM_KINDS = new Set(['CLAIM_INTAKE', 'CONTAINMENT', 'TEST_REQUEST', 'TEST_RESULT', 'REPRODUCTION']);
export const CLAIM_KIND_LABELS = { CLAIM_INTAKE: '클레임 접수', CONTAINMENT: '생산 중단 · 출고 보류 요청', TEST_REQUEST: '테스트 의뢰',
  TEST_RESULT: '테스트 결과', REPRODUCTION: '재생산 · A 요청서' };
const DOC_STATUS = { DRAFT: '검토 전', REVIEWED: '검토 완료', APPROVED: '승인 · 반영 전', POSTED: '원장 반영' };
const BOARD_STATUS = { PRODUCED: '생산 완료 · 입고 전', RECEIVED: '창고 보관', SHIPPED: '운송 중', ARRIVED: '고객 도착' };
const SAMPLES = [['claim_mail.eml', '메일 (.eml)'], ['claim_sheet.xlsx', '엑셀 (.xlsx)'], ['claim_table.csv', '표 (.csv)']];
const OUTCOMES = [['fail', '불량 재현'], ['pass', '정상'], ['not_reproduced', '재현 안 됨']];
const DISPOSITIONS = [['customer_replacement', '고객 교체'], ['stock_replacement', '재고 교체'], ['no_action', '조치 없음'], ['unresolved', '판단 보류']];
const ASSESSMENT = { confirmed: '확정', lower_bound: '최소 수량 (결과 미정 보드 있음)', undetermined: '판단 불가' };
const ERRORS = {
  SELF_REVIEW_FORBIDDEN: '작성한 계정은 검토할 수 없습니다. 다른 계정으로 전환해 검토·승인해 주세요.',
  SELF_APPROVAL_FORBIDDEN: '작성한 계정은 승인할 수 없습니다. 다른 계정으로 전환해 승인해 주세요.',
  CONTAINMENT_OUTSIDE_SCOPE: '봉쇄 요청 보드가 역추적 범위(생산 완료·창고 보관) 밖에 있습니다.',
  CONTAINMENT_ALREADY_REQUESTED: '같은 클레임에 같은 종류의 봉쇄 요청이 이미 있습니다.',
  TEST_RESULT_ALREADY_RECORDED: '이 테스트 의뢰의 결과는 이미 기록되었습니다.',
  REPRODUCTION_UNDETERMINED: '결과 미정 보드만 있어 재생산 수량을 정할 수 없습니다.',
  REPRODUCTION_QUANTITY_CHANGED: '재생산 수량 기준이 바뀌었습니다. 최신 원장을 다시 조회해 주세요.',
  REPRODUCTION_ALREADY_RECORDED: '이 테스트 결과의 재생산 요청서는 이미 있습니다.',
  PROCUREMENT_LEDGER_VERSION_CHANGED: '원장 기준이 바뀌었습니다. 최신 원장을 조회한 뒤 다시 시도해 주세요.',
  CLAIM_SAMPLE_NOT_ALLOWED: '저장소에 있는 합성 샘플만 변환할 수 있습니다.',
};

function nowWithOffset() {
  const d = new Date(), pad = n => String(n).padStart(2, '0'), offset = -d.getTimezoneOffset(), abs = Math.abs(offset);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    + `${offset >= 0 ? '+' : '-'}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export function mountClaims(container, { snapshot, api, getIdentity = () => null, onPosted = () => {}, onAsk = () => {}, onGraph = () => {} }) {
  const ledgerVersion = snapshot.meta?.ledger_version, pending = new Map();
  let view = null, documents = [], converted = null, busy = false, destroyed = false, notice = '', failed = false;
  const root = document.createElement('div'); root.className = 'claims';
  container.replaceChildren(root);
  const can = permission => (getIdentity()?.permitted_actions || []).includes(permission);
  const author = doc => doc?.created_by === getIdentity()?.actor_id;
  const exact = doc => ({ expected_version: doc.version, payload_hash: doc.payload_hash });
  const message = (text, error = false) => { notice = text; failed = error; };

  async function command(path, body) {
    const signature = JSON.stringify([path, body]);
    if (!pending.has(signature)) pending.set(signature, `claim-ui-${crypto.randomUUID()}`);
    const result = await api(path, { ...body, idempotency_key: pending.get(signature) });
    pending.delete(signature);
    return result;
  }
  async function load() {
    const [claims, list] = await Promise.all([api('/api/mks2/claims'), api('/api/mks2/procurement/documents')]);
    if (destroyed) return;
    view = claims; documents = (list.documents || []).filter(doc => CLAIM_KINDS.has(doc.kind));
  }
  async function work(callback) {
    if (busy || destroyed) return;
    busy = true; render();
    try { await callback(); }
    catch (error) {
      if (error.name === 'AbortError') return;
      message(ERRORS[error.message] || (error.status === 403 ? '현재 계정에는 이 작업 권한이 없습니다.'
        : error.status === 409 ? '문서 상태나 원장 기준이 바뀌었습니다. 최신 원장을 조회해 주세요.'
        : error.status === 422 ? `입력을 확인해 주세요 (${error.message}).` : '서버 결과를 확인하지 못했습니다. 같은 입력으로 다시 시도하면 같은 요청 키를 씁니다.'), true);
    } finally { if (!destroyed) { busy = false; render(); } }
  }
  const create = (content, done) => work(async () => {
    const result = await command('/api/mks2/procurement/documents', { expected_ledger_version: ledgerVersion, content });
    if (destroyed) return;
    await load();
    message(`${CLAIM_KIND_LABELS[content.kind]} 초안을 저장했습니다 (${result.id}). 다른 계정으로 검토·승인한 뒤 원장에 반영하세요.`);
    done?.();
  });

  const actions = {
    convert: sample => work(async () => {
      converted = await api('/api/mks2/claims/convert', { sample, collected_at: nowWithOffset() });
      message(converted.draft ? '변환 결과를 확인한 뒤 접수 초안으로 저장하세요. 신고 내용이며 불량 확정이 아닙니다.'
        : '변환 결과에 사람 확인이 필요한 항목이 있어 접수 초안을 만들지 않았습니다.', !converted.draft);
    }),
    intake: () => converted?.draft && create(converted.draft, () => { converted = null; }),
    approve: doc => work(async () => {
      const reviewed = doc.status === 'REVIEWED' ? doc : await command(`/api/mks2/procurement/documents/${encodeURIComponent(doc.id)}/review`, exact(doc));
      if (destroyed) return;
      await command(`/api/mks2/procurement/documents/${encodeURIComponent(doc.id)}/approve`, exact(reviewed));
      await load(); message('검토하고 승인했습니다. 원장 반영은 별도 단계입니다.');
    }),
    post: doc => work(async () => {
      const result = await command(`/api/mks2/procurement/documents/${encodeURIComponent(doc.id)}/post`, exact(doc));
      if (destroyed) return;
      await load(); onPosted(result);
      message('원장에 반영했습니다. 그래프 투영 후 클레임 노드가 함께 표시됩니다.');
    }),
  };

  function followups(claim) {
    const parts = [];
    const used = new Set(claim.containments.map(c => c.request_type));
    const stop = claim.scope_by_status.PRODUCED || [], hold = claim.scope_by_status.RECEIVED || [];
    for (const [type, serials, label] of [['PRODUCTION_STOP', stop, '생산 중단 요청'], ['SHIPMENT_HOLD', hold, '출고 보류 요청']]) {
      const disabled = busy || !serials.length || used.has(type) || !can('document.create');
      parts.push(`<button class="btn sm" data-act="contain" data-type="${type}" data-claim="${esc(claim.intake_document_id)}" ${disabled ? 'disabled' : ''}>${label} · ${serials.length}대</button>`);
    }
    const linked = claim.claimed.filter(u => u.match_state === 'LINKED').map(u => u.serial);
    if (!claim.test_requests.length) {
      parts.push(`<button class="btn sm primary" data-act="test-request" data-claim="${esc(claim.intake_document_id)}" ${busy || !linked.length || !can('document.create') ? 'disabled' : ''}>테스트 의뢰 · 신고 보드 ${linked.length}대</button>`);
    }
    return `<div class="claims-actions">${parts.join('')}</div>`;
  }
  function resultForm(claim, request) {
    if (claim.test_results.some(r => r.test_request_id === request.document_id)) return '';
    const rows = request.board_serials.map(serial => `<tr><td class="mono">${esc(serial)}</td>
      <td><select data-outcome="${esc(serial)}">${OUTCOMES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></td>
      <td><select data-disposition="${esc(serial)}">${DISPOSITIONS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></td></tr>`).join('');
    return `<form class="claims-result" data-request="${esc(request.document_id)}" data-ref="${esc(request.test_request_ref)}">
      <p class="note">테스트팀이 돌려준 결과와 보드별 처리 결정을 기록합니다 (C가 대신 판정하지 않음).</p>
      <table><thead><tr><th>보드</th><th>결과</th><th>처리</th></tr></thead><tbody>${rows}</tbody></table>
      <button class="btn sm primary" type="submit" ${busy || !can('document.create') ? 'disabled' : ''}>테스트 결과 초안 저장</button></form>`;
  }
  function reproduction(claim, summary) {
    if (!summary) return '';
    const result = claim.test_results.find(r => r.test_request_id === summary.test_request_id);
    const done = result && claim.reproductions.some(r => r.test_result_id === result.document_id);
    const quantity = summary.required_good_quantity;
    const line = summary.assessment_state === 'undetermined'
      ? `재생산 수량 판단 불가 · 결과 미정 ${summary.unresolved_quantity}대`
      : `재생산 필요 양품 ${summary.assessment_state === 'lower_bound' ? '최소 ' : ''}<b>${quantity}대</b> = 고객 교체 ${summary.customer_replacement_quantity} + 재고 교체 ${summary.stock_replacement_quantity}`
        + (summary.unresolved_quantity ? ` · 결과 미정 ${summary.unresolved_quantity}` : '');
    const button = result && !done && summary.assessment_state !== 'undetermined'
      ? `<button class="btn sm primary" data-act="reproduce" data-result="${esc(result.document_id)}" data-qty="${quantity}" data-claim-ref="${esc(claim.claim_ref)}" ${busy || !can('document.create') ? 'disabled' : ''}>A 전달 요청서 초안 · 양품 ${quantity}대</button>` : '';
    return `<div class="claims-repro"><span class="pill ${summary.assessment_state === 'confirmed' ? 'ok' : 'warn'}">${ASSESSMENT[summary.assessment_state]}</span> ${line}
      <p class="note">창고 보드는 이번 납품 회차에 약속돼 있어 여유 재고로 빼지 않습니다.</p>${button}</div>`;
  }
  function claimCard(claim) {
    const boards = claim.claimed.map(unit => {
      const up = unit.upstream || {};
      const chain = (up.chain || []).map(step => `<span class="step">${esc(step.production_ref || step.inspection_ref || step.receipt_ref || step.quote_ref || step.kind)}</span>`).join('<span class="arrow">←</span>');
      return `<tr><td class="mono">${esc(unit.serial)}</td><td>${esc(unit.status_label)}</td>
        <td>${unit.match_state === 'LINKED' ? `${esc(unit.lot_code || '미기록')} · ${esc(up.supplier_id || '공급사 기록 없음(기초 LOT)')}` : '사람 확인 필요'}</td>
        <td class="chain">${chain}</td></tr>`;
    }).join('');
    const scope = Object.entries(claim.scope_by_status).filter(([, serials]) => serials.length)
      .map(([status, serials]) => `<div class="scope-row"><b>${BOARD_STATUS[status]} ${serials.length}대</b> <span class="mono">${serials.map(esc).join(', ')}</span></div>`).join('');
    const containments = claim.containments.map(c => `<li>${c.request_type === 'PRODUCTION_STOP' ? '생산 중단' : '출고 보류'} ${esc(c.containment_ref)} · ${c.quantity}대 · 미송부</li>`).join('');
    const tests = claim.test_requests.map(request => `<li>테스트 의뢰 ${esc(request.test_request_ref)} · ${request.board_serials.length}대 → ${esc(request.test_team || '테스트팀')}${resultForm(claim, request)}</li>`).join('');
    const repro = claim.reproduction_summaries.map(summary => reproduction(claim, summary)).join('');
    const sent = claim.reproductions.map(r => `<li>A 전달 요청서 ${esc(r.reproduction_ref)} · 양품 ${r.required_good_quantity}대 · 희망 기한 ${esc(r.requested_due_date)} · 미송부</li>`).join('');
    return `<article class="claims-card">
      <header><h3>${esc(claim.customer_name)} · ${esc(claim.claim_ref)}</h3>
        <span class="pill warn">신고 ${claim.claimed_qty}대 · 불량 확정 아님</span>
        <button class="btn sm" data-act="ask" data-ref="${esc(claim.claim_ref)}">질의창에서 묻기</button>
        <button class="btn sm" data-act="graph" data-id="${esc(claim.intake_document_id)}">그래프 근거</button></header>
      <p class="symptom">증상: ${esc(claim.reported_symptom)}</p>
      <h4>1 · 신고 보드 역추적 <small>보드 → 생산 실적 → 수입검사 → 입하 → 견적(공급사)</small></h4>
      <table class="claims-trace"><thead><tr><th>보드</th><th>현재 상태</th><th>LOT · 공급사</th><th>원장 기록 사슬</th></tr></thead><tbody>${boards}</tbody></table>
      ${claim.not_found_serials.length ? `<p class="warn-text">원장에 없는 번호: ${claim.not_found_serials.map(esc).join(', ')} · 사람 확인 필요</p>` : ''}
      <h4>2 · 영향 범위 <small>같은 생산 실적 · 같은 LOT · 생산 라인은 원장에 기록되지 않아 확인 불가</small></h4>
      <div class="claims-scope">${scope || '<p class="note">범위 보드 없음</p>'}</div>
      ${claim.untraceable_opening_boards ? '<p class="note">기초 보드(일련번호 없음)는 범위 안팎을 판단할 수 없습니다.</p>' : ''}
      <h4>3 · 봉쇄 · 테스트 · 재생산</h4>
      ${followups(claim)}
      <ul class="claims-list">${containments}${tests}${sent}</ul>${repro}
    </article>`;
  }
  function documentRows() {
    const open = documents.filter(doc => doc.status !== 'POSTED');
    if (!open.length) return '<p class="note">진행 중인 클레임 문서가 없습니다.</p>';
    return `<table class="claims-docs"><thead><tr><th>문서</th><th>상태</th><th>작성</th><th></th></tr></thead><tbody>${open.map(doc => {
      const mine = author(doc);
      const button = doc.status === 'APPROVED'
        ? `<button class="btn sm primary" data-act="post" data-doc="${esc(doc.id)}" ${busy || !can('document.post') ? 'disabled' : ''}>원장 반영</button>`
        : mine ? '<span class="note">다른 계정의 검토·승인 대기</span>'
        : `<button class="btn sm primary" data-act="approve" data-doc="${esc(doc.id)}" ${busy || !can('document.approve') ? 'disabled' : ''}>검토 · 승인</button>`;
      return `<tr><td>${CLAIM_KIND_LABELS[doc.kind]}<br><span class="mono">${esc(doc.id)}</span></td><td>${DOC_STATUS[doc.status] || esc(doc.status)}</td>
        <td>${mine ? '내 초안' : esc(doc.created_by)}</td><td>${button}</td></tr>`;
    }).join('')}</tbody></table>`;
  }
  function convertedCard() {
    if (!converted) return '';
    const report = converted.report, claim = report.claim || {};
    return `<div class="claims-converted"><p><b>${esc(claim.customer_name)}</b> · ${esc(claim.external_claim_id)} · 신고 ${report.claimed_quantity}대 · ${esc(report.format)}</p>
      <p class="mono">${(report.unit_candidates || []).map(u => esc(u.serial)).join(', ')}</p>
      <p class="note">원문 SHA-256 ${esc(String(report.sha256).slice(0, 12))}… · ${esc(report.locator)}</p>
      ${converted.draft ? `<button class="btn sm primary" data-act="intake" ${busy || !can('document.create') ? 'disabled' : ''}>확인 · 접수 초안 저장</button>` : ''}</div>`;
  }
  function render() {
    if (destroyed) return;
    const claims = view?.claims || [];
    root.innerHTML = `<section class="claims-head"><h2>클레임 대응</h2>
        <p class="note">원장 v${ledgerVersion} 기준 · 모든 수량과 보드는 서버 원장 기록에서 읽습니다 · 고객·생산·A에 자동 전송하지 않습니다.</p></section>
      ${notice ? `<p class="claims-notice ${failed ? 'error' : ''}" role="status">${esc(notice)}</p>` : ''}
      <section class="claims-box"><h3>클레임 접수 변환 <small>메일 · 엑셀 · 표 형식의 합성 샘플</small></h3>
        <div class="claims-actions">${SAMPLES.map(([file, label]) => `<button class="btn sm" data-act="convert" data-sample="${file}" ${busy ? 'disabled' : ''}>${label}</button>`).join('')}</div>
        ${convertedCard()}</section>
      <section class="claims-box"><h3>결재 대기 문서 <small>작성자와 다른 계정이 검토·승인 → 원장 반영</small></h3>${documentRows()}</section>
      ${view ? (claims.length ? claims.map(claimCard).join('') : '<p class="note claims-empty">원장에 반영된 클레임 접수가 없습니다. 위에서 샘플을 변환해 접수하세요.</p>')
        : '<p class="note">클레임 기록을 읽는 중입니다.</p>'}`;
  }
  root.addEventListener('click', event => {
    const target = event.target.closest('[data-act]');
    if (!target || target.disabled) return;
    const act = target.dataset.act, doc = documents.find(row => row.id === target.dataset.doc);
    const claim = (view?.claims || []).find(row => row.intake_document_id === target.dataset.claim);
    if (act === 'convert') actions.convert(target.dataset.sample);
    else if (act === 'intake') actions.intake();
    else if (act === 'approve' && doc) actions.approve(doc);
    else if (act === 'post' && doc) actions.post(doc);
    else if (act === 'ask') onAsk(`${target.dataset.ref} 클레임 영향 범위와 재생산 수량 알려줘`);
    else if (act === 'graph') onGraph(target.dataset.id);
    else if (act === 'contain' && claim) {
      const type = target.dataset.type, serials = claim.scope_by_status[type === 'PRODUCTION_STOP' ? 'PRODUCED' : 'RECEIVED'];
      create({ kind: 'CONTAINMENT', claim_intake_id: claim.intake_document_id, containment_ref: `${claim.claim_ref}-${type === 'PRODUCTION_STOP' ? 'STOP' : 'HOLD'}`,
        request_type: type, board_serials: serials, quantity: serials.length, note: '역추적 범위 기반 내부 요청 · 미송부' });
    } else if (act === 'test-request' && claim) {
      const serials = claim.claimed.filter(u => u.match_state === 'LINKED').map(u => u.serial);
      create({ kind: 'TEST_REQUEST', claim_intake_id: claim.intake_document_id, test_request_ref: `${claim.claim_ref}-TR1`,
        board_serials: serials, quantity: serials.length, note: '신고 보드 테스트 의뢰' });
    } else if (act === 'reproduce') {
      create({ kind: 'REPRODUCTION', test_result_id: target.dataset.result, reproduction_ref: `${target.dataset.claimRef}-RP`,
        quantity: Number(target.dataset.qty), note: '서버가 테스트 결과로 계산한 수량 · A에 미송부' });
    }
  });
  root.addEventListener('submit', event => {
    const form = event.target.closest('form.claims-result');
    if (!form) return;
    event.preventDefault();
    const results = [...form.querySelectorAll('[data-outcome]')].map(select => ({ serial: select.dataset.outcome, outcome: select.value,
      disposition: form.querySelector(`[data-disposition="${CSS.escape(select.dataset.outcome)}"]`).value }));
    create({ kind: 'TEST_RESULT', test_request_id: form.dataset.request, test_result_ref: `${form.dataset.ref}-RES`,
      results, quantity: results.length, note: '테스트팀 결과와 보드별 처리 결정 기록' });
  });
  render();
  work(load);
  return { destroy() { destroyed = true; root.remove(); }, refresh: () => work(load) };
}
