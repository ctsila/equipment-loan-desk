const get = selector => document.querySelector(selector);
const accountPicker = get('#account');
const form = get('#request-form');
const labels = {
  pending_manager: 'Awaiting manager', pending_it: 'Awaiting local IT', approved: 'Approved', rejected: 'Declined'
};
const errors = {
  invalid_fields: 'Complete all five fields before sending the request.',
  required_fields: 'Complete all five fields before sending the request.',
  reason_too_short_or_long: 'Write a reason of 15–300 characters with at least three words.',
  profile_mismatch: 'Enter the name, employee ID and office for the selected account.',
  open_request_limit_reached: 'This company has reached its open request limit.',
  decline_reason_required: 'Enter a reason for declining the request.',
  invalid_decision: 'Check the decision and keep the explanation within 200 characters.',
  wrong_approval_stage: 'This request is waiting for a different approval or is already closed.',
  request_not_found: 'This request is unavailable in your workspace.'
};
let profile;
let token;

async function api(path, key, body) {
  const headers = key ? {Authorization: `Bearer ${key}`} : {};
  const options = {headers};
  if (body !== undefined) {
    options.method = 'POST';
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(errors[data.error] || 'The request could not be completed.');
  return data;
}

function notice(text, failed = false) {
  const box = get('#message');
  box.textContent = text;
  box.hidden = !text;
  box.classList.toggle('error', failed);
}

function element(tag, text, classes) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (classes) node.className = classes;
  return node;
}

function choice(value, label) {
  const option = element('option', label);
  option.value = value;
  return option;
}

function reviewStep(name, decision, note, skipped = false) {
  const status = skipped ? 'step skipped' : decision === 'approve' ? 'approved' : decision === 'reject' ? 'declined' : 'pending';
  const step = element('li', `${name} · ${status}`);
  if (decision === 'reject' && note) {
    step.append(element('p', `Decline reason: ${note}`, 'decline-reason'));
  }
  return step;
}

function reviewControls(id) {
  const controls = element('div', '');
  const actions = element('div', '', 'actions');
  const approve = element('button', 'Approve', 'primary');
  const decline = element('button', 'Decline');
  actions.append(approve, decline);

  const declineForm = element('form', '', 'decline-form');
  declineForm.hidden = true;
  const reason = element('textarea', '');
  reason.required = true;
  reason.maxLength = 200;
  reason.rows = 2;
  const label = element('label', 'Reason for declining (required)', 'field');
  label.append(reason);
  const formActions = element('div', '', 'actions');
  const confirm = element('button', 'Confirm decline', 'danger');
  confirm.type = 'submit';
  const cancel = element('button', 'Cancel');
  cancel.type = 'button';
  formActions.append(confirm, cancel);
  declineForm.append(label, formActions);
  controls.append(actions, declineForm);

  approve.addEventListener('click', () => changeDecision(id, 'approve', controls));
  decline.addEventListener('click', () => {
    actions.hidden = true;
    declineForm.hidden = false;
    reason.focus();
  });
  cancel.addEventListener('click', () => {
    declineForm.reset();
    reason.setCustomValidity('');
    declineForm.hidden = true;
    actions.hidden = false;
    decline.focus();
  });
  reason.addEventListener('input', () => reason.setCustomValidity(''));
  declineForm.addEventListener('submit', event => {
    event.preventDefault();
    const note = reason.value.trim();
    if (!note) {
      reason.setCustomValidity('Enter a reason for declining the request.');
      reason.reportValidity();
      return;
    }
    changeDecision(id, 'reject', controls, note);
  });
  return controls;
}

function showRequests(data) {
  get('#usage').textContent = `${data.plan} · ${data.open} of ${data.limit} open requests`;
  const list = get('#request-list');
  list.replaceChildren();
  if (!data.requests.length) {
    list.append(element('p', profile.role === 'employee' ? 'You have no equipment requests yet.' : 'There are no requests in your review queue.', 'empty'));
    return;
  }
  for (const item of data.requests) {
    const card = element('article', '', 'request');
    card.dataset.requestId = item.id;
    const heading = element('div', '', 'request-heading');
    heading.append(element('h3', item.equipment), element('span', labels[item.status], `status ${item.status}`));
    const route = element('ol', '', 'route-list');
    route.append(reviewStep(item.manager_name, item.manager_decision, item.manager_note),
      reviewStep(item.it_team, item.it_decision, item.it_note, item.manager_decision === 'reject'));
    card.append(heading, element('p', `${item.employee_name} · ${item.employee_id} · ${item.office}, ${item.region}`, 'request-meta'),
      element('p', item.reason), route);
    const canAct = (profile.role === 'manager' && item.status === 'pending_manager') ||
                   (profile.role === 'it' && item.status === 'pending_it');
    if (canAct) card.append(reviewControls(item.id));
    list.append(card);
  }
}

async function reload(key) {
  const items = await api('/v1/requests', key);
  if (key === token) showRequests(items);
}

async function changeDecision(id, decision, controls, note) {
  const key = token;
  const fields = [...controls.querySelectorAll('button, textarea')];
  fields.forEach(field => field.disabled = true);
  try {
    const body = note === undefined ? {decision} : {decision, note};
    const item = await api(`/v1/requests/${id}/decision`, key, body);
    if (token !== key) return;
    await reload(key);
    if (token === key) notice(item.status === 'pending_it' ? 'Manager approved. The request was sent to local IT.' :
                              item.status === 'approved' ? 'IT approved the request.' : 'The request was declined. The employee can see your reason.');
  } catch (error) {
    if (token === key) notice(error.message, true);
  } finally {
    fields.forEach(field => field.disabled = false);
  }
}

async function openWorkspace(key) {
  token = key;
  notice('');
  get('#workspace-grid').hidden = true;
  try {
    const result = await api('/v1/me', key);
    if (token !== key) return;
    profile = result.profile;
    const isEmployee = profile.role === 'employee';
    const isManager = profile.role === 'manager';
    get('#workspace').textContent = `${profile.company} / ${profile.office}, ${profile.region}`;
    get('#page-title').textContent = isEmployee ? 'Request equipment' : isManager ? 'Manager review' : 'IT review';
    get('#description').textContent = isEmployee ? 'Send a request and follow its two approvals.' :
      isManager ? 'Review equipment requests from your direct reports.' : 'Review manager-approved requests for your office.';
    get('#queue-title').textContent = isEmployee ? 'My requests' : 'Review queue';
    get('#employee-panel').hidden = !isEmployee;
    get('#workspace-grid').classList.toggle('review', !isEmployee);
    if (isEmployee) {
      get('#route').textContent = `Approval route: ${profile.manager_name}, then ${profile.office} IT.`;
      get('#equipment').replaceChildren(choice('', 'Select equipment'), ...result.equipment.map(e => choice(e, e)));
      get('#office').replaceChildren(choice('', 'Select your office'), ...Object.entries(result.offices).map(([city, region]) => choice(city, `${city}, ${region}`)));
      form.reset();
      form.elements.employee_name.placeholder = profile.name;
      form.elements.employee_id.placeholder = profile.id;
    }
    await reload(key);
    if (token === key) get('#workspace-grid').hidden = false;
  } catch (error) {
    if (token === key) notice(error.message, true);
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const key = token;
  const submit = form.querySelector('button[type=submit]');
  submit.disabled = true;
  try {
    await api('/v1/requests', key, Object.fromEntries(new FormData(form)));
    if (token !== key) return;
    form.reset();
    await reload(key);
    if (token === key) notice('Request sent to your manager.');
  } catch (error) {
    if (token === key) notice(error.message, true);
  } finally {
    submit.disabled = false;
  }
});

accountPicker.addEventListener('change', () => openWorkspace(accountPicker.value));
api('/demo/accounts').then(accounts => {
  for (const account of accounts) {
    accountPicker.append(choice(account.token, `${account.name} · ${account.role.toUpperCase()} · ${account.company}`));
  }
  return openWorkspace(accountPicker.value);
}).catch(error => notice(error.message, true));
