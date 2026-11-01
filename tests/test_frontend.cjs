'use strict';
// Dependency-free model/security checks against the shipped HTML. DOM stubs
// exercise rendering and clock selectors; these are not browser-layout tests.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const scripts = Array.from(html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi), match => match[1]);
const calendar = scripts.find(source => source.includes('global.FamilyDates = Object.freeze'));
const application = scripts.find(source => source.includes('function validateImport(value)'));
assert(calendar && application, 'The single HTML must contain the calendar and application code.');
const expose = `globalThis.__frontendTests={initial,validateImport,esc,field,eventEditor,
  clock,renderCalendar,eventRows,itemRows,taskRows,weekStrip,render,
  renderToday,renderShopping,renderNotes,renderSettings,completeTask,mutate,
  getState:()=>state,setState:value=>{state=value;},setError:value=>{error=value;},
  setSession:(value={})=>{
    me=value.role===null?null:{id:'test-user',name:'Test user',role:value.role||'adult'};
    view=value.view||'today';calendarView=value.calendarView||'week';
    selected=value.selected||D.today(state.preferences.timezone);
    location.pathname=value.pathname||'/index.html';location.hash=value.hash||'';clockDay='';
  }};})();`;
const instrumented = application.replace(/boot\(\);\s*\}\)\(\);\s*$/, expose);
assert.notEqual(instrumented, application, 'Instrumentation must replace only the final automatic boot.');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    id, hidden: false, value: '', textContent: '', innerHTML: '', dataset: {},
    addEventListener() {}, close() {}, showModal() {}, focus() {},
    classList: { toggle() {}, remove() {}, add() {} }
  });
  return nodes.get(id);
}
const memory = new Map();
let clockTargets = [];
const sandbox = {
  Date, Intl, RangeError, TypeError, Promise, URL, Blob,
  crypto: { randomUUID },
  location: { protocol: 'file:', pathname: '/index.html', hash: '', origin: 'null' },
  document: {
    activeElement: null, hidden: false,
    getElementById: element, addEventListener() {},
    querySelectorAll(selector) {
      const attribute = /^\[(data-[\w-]+)\]$/.exec(selector);
      return attribute ? clockTargets.filter(node => Object.hasOwn(node.attributes, attribute[1])) : [];
    },
    documentElement: { dataset: {} }, body: { classList: { toggle() {}, remove() {} } }
  },
  localStorage: { getItem(key) { return memory.get(key) || null; }, setItem(key, value) { memory.set(key, value); } },
  fetch() { throw new Error('A pure frontend test must not make network requests.'); },
  addEventListener() {}, setInterval() {}, setTimeout() { return 1; }, clearTimeout() {}
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(calendar, sandbox, { filename: 'index.html:calendar', timeout: 1000 });
vm.runInContext(instrumented, sandbox, { filename: 'index.html:application', timeout: 1000 });
const api = sandbox.__frontendTests;
const copy = value => JSON.parse(JSON.stringify(value));
const fresh = () => copy(api.initial());
const event = overrides => ({ id: 'event-1', title: 'Family dinner', date: '2026-10-31',
  time: '18:00', endTime: '19:00', allDay: false, memberId: 'family', repeat: 'weekly',
  until: '', exceptions: [], description: '', location: '', reminder: 30, private: false, ...overrides });
const text = markup => markup.replace(/<[^>]*>/g, '').trim();
function buttons(markup) {
  return Array.from(markup.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/gi), match => ({
    attributes: match[1], label: text(match[2]), markup: match[0]
  }));
}
function mountClockTargets(markup) {
  // Model only attribute selection and textContent replacement, which caused the
  // original bug. Targets come from the application's real rendered markup.
  const targets = [
    ...Array.from(markup.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/gi)),
    ...Array.from(markup.matchAll(/<div\b([^>]*\bdata-clock(?:-date)?\b[^>]*)>([^<]*)<\/div>/gi))
  ];
  clockTargets = targets.map(match => ({
    attributes: Object.fromEntries(Array.from(match[1].matchAll(/\b(data-[\w-]+)(?:="([^"]*)")?/g), attribute => [attribute[1], attribute[2] || ''])),
    textContent: text(match[2])
  }));
  return clockTargets;
}
function assertVisibleEdit(markup, action, id) {
  assert(buttons(markup).some(button =>
    button.attributes.includes('data-action="' + action + '"') &&
    button.attributes.includes('data-id="' + id + '"') &&
    /\bEdit\b/.test(button.label)), 'Expected a visible Edit button for ' + action);
}
function assertReadOnlyRows(markup) {
  assert(!/data-action="(?:event|task|item|toggle-task|toggle-item)"/.test(markup), 'Read-only rows must not advertise editing or completion actions.');
  assert(!buttons(markup).some(button => /\bEdit\b/.test(button.label)));
}

test('initial state is valid and independent between new households', () => {
  const one = fresh();
  one.members[0].name = 'Changed';
  assert.equal(fresh().members[0].name, 'Family');
  assert.equal(api.validateImport(fresh()).preferences.timezone, 'UTC');
});

test('export-shaped imports preserve valid recurrence and household records', () => {
  const state = fresh();
  state.events.push(event({ exceptions: ['2026-11-07'] }));
  state.items.push({ id: 'item-1', title: 'Milk', quantity: '2 L', category: 'Dairy', list: 'Groceries', done: false, completedAt: '' });
  const result = api.validateImport({ format: 'homeboard-backup', version: 1, state });
  assert.deepEqual(copy(result.events[0].exceptions), ['2026-11-07']);
  assert.equal(result.items[0].quantity, '2 L');
});

test('backup imports retain chosen weekly recurrence days', () => {
  const state = fresh();
  state.events = [event({ weekdays: [1, 3, 5] })];
  assert.deepEqual(copy(api.validateImport(state).events[0].weekdays), [1, 3, 5]);
  state.events[0].weekdays = [1, 1];
  assert.throws(() => api.validateImport(state), /weekday/i);
});

test('rejects duplicate and markup-bearing identifiers', () => {
  const duplicate = fresh();
  duplicate.events = [event(), event()];
  assert.throws(() => api.validateImport(duplicate), /duplicate|identifier/i);
  const injected = fresh();
  injected.events = [event({ id: 'event"><img src=x>' })];
  assert.throws(() => api.validateImport(injected), /identifier/i);
});

test('rejects missing family profile and invalid member references', () => {
  const missing = fresh();
  missing.members = missing.members.filter(member => member.id !== 'family');
  assert.throws(() => api.validateImport(missing), /family profile/i);
  const orphan = fresh();
  orphan.events = [event({ memberId: 'not-a-member' })];
  assert.throws(() => api.validateImport(orphan), /member.*missing/i);
});

test('rejects impossible/out-of-range dates, exceptions and time values', () => {
  for (const overrides of [
    { date: '2026-02-30' }, { date: '1800-01-01' }, { date: '2201-01-01' },
    { time: '24:00' }, { until: '2026-01-01' }, { exceptions: ['2026-02-29'] }
  ]) {
    const state = fresh();
    state.events = [event(overrides)];
    assert.throws(() => api.validateImport(state), /invalid|between|precedes/i);
  }
});

test('rejects unsupported recurrence, flags and reminder choices', () => {
  for (const overrides of [{ repeat: 'hourly' }, { private: 'true' }, { allDay: 'false' }, { reminder: 999 }]) {
    const state = fresh();
    state.events = [event(overrides)];
    assert.throws(() => api.validateImport(state), /invalid|unsupported|must be/i);
  }
});

test('rejects invalid meal dates, malformed collections and oversized payload collections', () => {
  const badMeal = fresh();
  badMeal.meals = { '__proto__': 'ignored object prototype', '2026-02-30': 'Soup' };
  assert.throws(() => api.validateImport(badMeal), /invalid.*date/i);
  const malformed = fresh();
  malformed.items = {};
  assert.throws(() => api.validateImport(malformed), /items collection/i);
  const excessive = fresh();
  excessive.notes = Array.from({ length: 301 }, (_, i) => ({ id: 'note-' + i, text: 'a', expires: '', private: false }));
  assert.throws(() => api.validateImport(excessive), /notes collection/i);
});

test('rejects unsupported theme/timezone and strips unknown input fields', () => {
  const badTheme = fresh();
  badTheme.preferences.theme = 'remote-script';
  assert.throws(() => api.validateImport(badTheme), /theme/i);
  const badZone = fresh();
  badZone.preferences.timezone = 'Not/A_Timezone';
  assert.throws(() => api.validateImport(badZone), /time.?zone/i);
  const extra = fresh();
  extra.unsafeExtra = '<script>run()</script>';
  extra.preferences.unsafeExtra = 'x';
  const result = api.validateImport(extra);
  assert.equal(Object.hasOwn(result, 'unsafeExtra'), false);
  assert.equal(Object.hasOwn(result.preferences, 'unsafeExtra'), false);
});

test('escaped user text cannot turn into markup in input fields or rendered panels', () => {
  const payload = '<img src=x onerror="globalThis.pwned=true">';
  assert.equal(api.esc('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
  assert(api.field('Name', 'name', payload).includes('&lt;img'));
  assert(!api.field('Name', 'name', payload).includes('<img'));
  const state = fresh();
  state.members[0].name = payload;
  state.preferences.household = payload;
  state.events = [event({ title: payload, description: payload, location: payload, date: sandbox.FamilyDates.today() })];
  state.items = [{ id: 'item-1', title: payload, quantity: payload, category: payload, list: 'Groceries', done: false, completedAt: '' }];
  state.notes = [{ id: 'note-1', text: payload, expires: '', private: false }];
  api.setState(state);
  for (const renderer of [api.renderToday, api.renderShopping, api.renderNotes, api.renderSettings]) {
    const result = renderer();
    assert(result.includes('&lt;img'));
    assert(!result.includes('<img'));
  }
  assert.equal(sandbox.pwned, undefined);
});

test('completing monthly tasks creates one correctly anchored next occurrence', async () => {
  const state = fresh();
  state.tasks = [{ id: 'task-monthly', title: 'Pay the bill', due: '2026-01-31', memberId: 'family', repeat: 'monthly', done: false, completedAt: '', seriesId: '' }];
  api.setState(state);
  assert.equal(await api.completeTask('task-monthly'), true);
  let result = api.getState();
  assert.equal(result.tasks.length, 2);
  assert.equal(result.tasks[0].done, true);
  assert.equal(result.tasks[1].due, '2026-03-31');
  assert.equal(result.tasks[1].seriesId, 'task-monthly');
  assert.equal(await api.completeTask(result.tasks[1].id), true);
  result = api.getState();
  assert.equal(result.tasks[2].due, '2026-05-31');
});

test('yearly leap tasks keep their calendar anchor and cannot reopen repeating history', async () => {
  const state = fresh();
  state.tasks = [{ id: 'task-leap', title: 'Leap day task', due: '2096-02-29', memberId: 'family', repeat: 'yearly', done: false, completedAt: '', seriesId: '' }];
  api.setState(state);
  assert.equal(await api.completeTask('task-leap'), true);
  assert.equal(api.getState().tasks[1].due, '2104-02-29');
  assert.equal(await api.completeTask('task-leap'), false);
  assert.equal(api.getState().tasks.length, 2);
});

test('failed local persistence is reported rather than acknowledged as a successful edit', async () => {
  api.setState(fresh());
  const original = sandbox.localStorage.setItem;
  sandbox.localStorage.setItem = () => { throw new Error('Quota exceeded'); };
  try {
    const saved = await api.mutate(state => state.notes.push({ id: 'test', text: 'Keep me', expires: '', private: false }), 'Saved');
    assert.equal(saved, false);
  } finally { sandbox.localStorage.setItem = original; }
});


test('the event editor includes seven selectable weekdays in its weekly repeat section', () => {
  api.setState(fresh());api.setError('');
  api.eventEditor();
  const markup=nodes.get('dialog-fields').innerHTML;
  for(const day of ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']) {
    assert(markup.includes('aria-label="'+day+'"'));
  }
  assert.equal((markup.match(/name="weekdays"/g)||[]).length,7);
});

test('calendar week columns keep distinct dates and the correct event in each day', () => {
  const state = fresh();
  const start = sandbox.FamilyDates.weekStart('2026-10-31');
  const dates = Array.from({ length: 7 }, (_, i) => sandbox.FamilyDates.addDays(start, i));
  state.events = dates.map((date, i) => event({ id: 'week-' + i, title: 'Plan for ' + date, date, repeat: 'none' }));
  api.setState(state);
  api.setSession({ view: 'calendar', calendarView: 'week', selected: '2026-10-31' });
  const markup = api.renderCalendar();
  const columns = Array.from(markup.matchAll(/<section\b[^>]*>([\s\S]*?)<\/section>/g), match => match[1]);
  assert.equal(columns.length, 7);
  columns.forEach((column, i) => {
    const heading = /<div class="calendar-day-heading"><span>([^<]+)<\/span><strong>(\d+)<\/strong><\/div>/.exec(column);
    assert(heading, 'Each day has a readable weekday and date heading.');
    const expected = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short' }).format(new Date(dates[i] + 'T12:00:00Z'));
    assert.equal(heading[1], expected);
    assert.equal(Number(heading[2]), Number(dates[i].slice(-2)));
    const plans = buttons(column).filter(button => /data-id="week-/.test(button.attributes));
    assert.equal(plans.length, 1);
    assert(plans[0].attributes.includes('data-date="' + dates[i] + '"'));
    assert(plans[0].label.includes('Plan for ' + dates[i]));
  });
});

test('clock ticks update only the header and preserve calendar action labels in every view', () => {
  const state = fresh();
  state.events = [
    event({ title: 'Saturday picnic', repeat: 'none' }),
    event({ id: 'event-2', title: 'Monday appointment', date: '2026-10-26', repeat: 'none' })
  ];
  api.setState(state);
  for (const calendarView of ['week', 'month', 'day']) {
    clockTargets = [];
    api.setSession({ view: 'calendar', calendarView, selected: '2026-10-31' });
    api.render();
    const markup = nodes.get('app').innerHTML;
    const mounted = mountClockTargets(markup);
    const dateHeaders = mounted.filter(node => Object.hasOwn(node.attributes, 'data-clock-date'));
    const timeHeaders = mounted.filter(node => Object.hasOwn(node.attributes, 'data-clock'));
    const actions = mounted.filter(node => Object.hasOwn(node.attributes, 'data-date'));
    assert.equal(dateHeaders.length, 1, 'The header needs its own clock date hook.');
    assert.equal(timeHeaders.length, 1);
    assert(actions.length > 0, calendarView + ' must include dated calendar controls.');
    const before = actions.map(node => ({ attributes: { ...node.attributes }, label: node.textContent }));
    api.clock();
    api.clock();
    assert.match(timeHeaders[0].textContent, /\d{1,2}:\d{2}/);
    assert.match(dateHeaders[0].textContent, /\p{L}+.*\d|\d.*\p{L}+/u);
    assert.deepEqual(actions.map(node => ({ attributes: { ...node.attributes }, label: node.textContent })), before,
      calendarView + ' labels must survive repeated clock ticks.');
    assert(actions.some(node => node.textContent.includes('Saturday picnic')), 'Event titles remain readable.');
    if (calendarView === 'month') {
      const dayNumbers = actions.filter(node => /^\d{1,2}$/.test(node.textContent));
      assert(dayNumbers.length >= 28, 'Month day buttons retain their numeric labels.');
      assert(new Set(dayNumbers.map(node => node.textContent)).size >= 28);
    }
  }
  clockTargets = [];
});

test('adults see explicit Edit actions for existing events, tasks and shopping items', () => {
  api.setState(fresh());
  api.setSession({ role: 'adult' });
  const occurrence = event({ occurrenceDate: '2026-10-31' });
  const task = { id: 'task-edit', title: 'Water plants', due: '2026-10-31', memberId: 'family', repeat: 'none', done: false };
  const item = { id: 'item-edit', title: 'Apples', quantity: '4', done: false };
  assertVisibleEdit(api.eventRows([occurrence]), 'event', occurrence.id);
  assertVisibleEdit(api.taskRows([task]), 'task', task.id);
  assertVisibleEdit(api.itemRows([item]), 'item', item.id);
});

test('display accounts and adult display previews render rows without editing actions', () => {
  const state = fresh();
  state.events = [event({ date: sandbox.FamilyDates.today(state.preferences.timezone), repeat: 'none' })];
  api.setState(state);
  const occurrence = { ...state.events[0], occurrenceDate: state.events[0].date };
  const task = { id: 'task-readonly', title: 'Water plants', due: '', memberId: 'family', repeat: 'none', done: false };
  const item = { id: 'item-readonly', title: 'Apples', quantity: '4', done: false };
  for (const session of [{ role: 'display' }, { role: 'adult', pathname: '/display' }, { role: 'adult', hash: '#display' }]) {
    api.setSession(session);
    for (const markup of [api.eventRows([occurrence]), api.taskRows([task]), api.itemRows([item]), api.weekStrip()]) {
      assertReadOnlyRows(markup);
    }
  }
});

test('the next seven days retain their dates and offer adults a visible event Edit action', () => {
  const state = fresh();
  const from = sandbox.FamilyDates.today(state.preferences.timezone);
  const dates = Array.from({ length: 7 }, (_, i) => sandbox.FamilyDates.addDays(from, i));
  state.events = dates.map((date, i) => event({ id: 'strip-' + i, title: 'Strip plan ' + i, date, repeat: 'none' }));
  api.setState(state);
  api.setSession({ role: 'adult' });
  const markup = api.weekStrip();
  const dayNumbers = Array.from(markup.matchAll(/<strong>(\d+)<\/strong>/g), match => Number(match[1]));
  assert.deepEqual(dayNumbers, dates.map(date => Number(date.slice(-2))));
  dates.forEach((date, i) => {
    const control = buttons(markup).find(button => button.attributes.includes('data-id="strip-' + i + '"'));
    assert(control, 'Each upcoming plan has an action.');
    assert(control.attributes.includes('data-date="' + date + '"'));
    assert(control.label.includes('Strip plan ' + i));
    assert(/\bEdit\b/.test(control.label), 'Upcoming plans make editing discoverable.');
  });
});

test('adult display mode has an Edit dashboard link while display accounts stay read-only', () => {
  api.setState(fresh());
  for (const session of [{ role: 'adult', pathname: '/display' }, { role: 'adult', hash: '#display' }]) {
    api.setSession(session);
    api.render();
    const markup = nodes.get('app').innerHTML;
    assert(/<a\b[^>]*href="#"[^>]*>[\s\S]*?Edit dashboard[\s\S]*?<\/a>/.test(markup),
      'Adults can return from the display preview to the editable dashboard.');
  }
  api.setSession({ role: 'display', pathname: '/display' });
  api.render();
  assert(!nodes.get('app').innerHTML.includes('Edit dashboard'));
  api.setSession({ role: 'adult' });
});


test('adult display previews mask private events and notes without altering the original records', () => {
  const state=fresh(),today=sandbox.FamilyDates.today();
  state.events=[event({title:'A private appointment',description:'Private detail',location:'Private place',private:true,date:today})];
  state.notes=[{id:'private-note',text:'Private family note',private:true,expires:''}];
  api.setState(state);api.setSession({role:'admin',pathname:'/display'});
  const preview=api.renderToday();
  assert.match(preview,/Busy/);
  for(const hidden of ['A private appointment','Private detail','Private place','Private family note'])assert(!preview.includes(hidden));
  assert.equal(api.getState().events[0].title,'A private appointment');
  api.setSession({role:'admin',pathname:'/'});
  assert.match(api.renderToday(),/A private appointment/);
});
