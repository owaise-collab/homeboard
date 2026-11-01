'use strict';
// Run with node --test tests/test_dates.cjs. Tests exercise the engine embedded
// in the actual deliverable, not a separately maintained implementation copy.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const filename = path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(filename, 'utf8');
const inlineScripts = Array.from(html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi));
let checkedScripts = 0;
for (const [_, attributes, source] of inlineScripts) {
  if (/\bsrc\s*=/i.test(attributes)) continue;
  if (/\btype\s*=\s*["'](?:application\/ld\+json|application\/json)["']/i.test(attributes)) continue;
  new vm.Script(source, { filename: 'index.html:inline-script-' + (++checkedScripts) });
}
assert(checkedScripts > 0, 'The HTML must contain an executable inline script.');

const match = html.match(/\/\* Dependency-free local-date calendar helpers\.[\s\S]*?\}\)\(typeof window !== 'undefined' \? window : globalThis\);/);
assert(match, 'The actual HTML must embed the FamilyDates engine.');
const sandbox = { Date, Intl, RangeError, TypeError };
vm.runInNewContext(match[0], sandbox, { filename: 'index.html:FamilyDates', timeout: 1000 });
const dates = sandbox.FamilyDates;
const event = overrides => ({ id: 'e', title: 'Family plan', date: '2026-01-01',
  time: '10:00', endTime: '', allDay: false, repeat: 'none', until: '', exceptions: [], ...overrides });
const keys = rows => Array.from(rows, row => row.occurrenceDate);

test('all inline JavaScript in the actual HTML passes syntax parsing', () => {
  assert(checkedScripts > 0);
  assert.equal(typeof dates.expandEvents, 'function');
});

test('uses neutral UTC by default and honors each household timezone explicitly', () => {
  assert.equal(dates.dateKey('2026-10-30T20:30:00Z'), '2026-10-30');
  assert.equal(dates.dateKey('2026-10-30T20:30:00Z', 'Asia/Yekaterinburg'), '2026-10-31');
  assert.equal(dates.dateKey('2026-10-30T20:30:00Z', 'America/New_York'), '2026-10-30');
  assert.throws(() => dates.dateKey('not a timestamp'), RangeError);
});

test('calendar arithmetic crosses month, year and leap boundaries without DST drift', () => {
  assert.equal(dates.addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(dates.addDays('2024-02-28', 1), '2024-02-29');
  assert.equal(dates.addDays('2026-03-01', -1), '2026-02-28');
  assert.equal(dates.addDays('2026-03-08', 1), '2026-03-09');
  assert.equal(dates.monthDays('2024-02-10'), 29);
  assert.equal(dates.monthDays('2026-02-10'), 28);
  assert.equal(dates.weekStart('2026-11-01'), '2026-10-26');
  assert.equal(dates.weekStart('2026-11-02'), '2026-11-02');
  assert.throws(() => dates.addDays('2026-02-30', 1), RangeError);
  assert.throws(() => dates.addDays('2026-01-01', 0.5), RangeError);
});

test('daily recurrence respects start, inclusive until and date exceptions', () => {
  const rows = dates.expandEvents([event({ date: '2026-10-31', repeat: 'daily',
    until: '2026-11-03', exceptions: ['2026-11-01'] })], '2026-10-30', '2026-11-05');
  assert.deepEqual(keys(rows), ['2026-10-31', '2026-11-02', '2026-11-03']);
  assert.equal(rows[0].key, 'e@2026-10-31');
});

test('weekly recurrence is anchored to the original local day', () => {
  assert.deepEqual(keys(dates.expandEvents([event({ date: '2026-10-31', repeat: 'weekly' })],
    '2026-11-01', '2026-11-15')), ['2026-11-07', '2026-11-14']);
});

test('weekly recurrence runs on selected weekdays across weeks and month boundaries', () => {
  const selected = event({ date: '2026-10-31', repeat: 'weekly', weekdays: [1, 3, 5] });
  assert.deepEqual(keys(dates.expandEvents([selected], '2026-10-30', '2026-11-09')),
    ['2026-11-02', '2026-11-04', '2026-11-06', '2026-11-09']);
  assert.equal(dates.nextOccurrence(selected, '2026-11-02'), '2026-11-04');
});

test('selected Sundays respect the start, inclusive end, and removed occurrences', () => {
  const selected = event({ date: '2026-10-31', repeat: 'weekly', weekdays: [6, 7],
    until: '2026-11-08', exceptions: ['2026-11-01'] });
  assert.deepEqual(keys(dates.expandEvents([selected], '2026-10-26', '2026-11-15')),
    ['2026-10-31', '2026-11-07', '2026-11-08']);
  for (const weekdays of [[0], [8], [1, 1], [true], ['1'], {}]) {
    assert(dates.validateEvent(event({ repeat: 'weekly', weekdays })).length);
  }
});

test('monthly 31st skips nonexistent days instead of moving into the following month', () => {
  assert.deepEqual(keys(dates.expandEvents([event({ date: '2026-01-31', repeat: 'monthly' })],
    '2026-01-01', '2026-05-31')), ['2026-01-31', '2026-03-31', '2026-05-31']);
});

test('yearly Feb 29 skips nonleap years and century exception', () => {
  const leap = event({ date: '2096-02-29', repeat: 'yearly' });
  assert.deepEqual(keys(dates.expandEvents([leap], '2100-01-01', '2100-12-31')), []);
  assert.deepEqual(keys(dates.expandEvents([leap], '2104-01-01', '2104-12-31')), ['2104-02-29']);
});

test('ranges are inclusive, bounded to 366 days and reject reversed dates', () => {
  assert.equal(dates.expandEvents([event({ repeat: 'daily', date: '2024-01-01' })],
    '2024-01-01', '2024-12-31').length, 366);
  assert.throws(() => dates.expandEvents([], '2024-01-01', '2025-01-01'), RangeError);
  assert.throws(() => dates.expandEvents([], '2026-11-02', '2026-11-01'), RangeError);
});

test('orders all-day before timed events per day, then chronologically', () => {
  const rows = dates.expandEvents([
    event({ id: 'later', time: '16:00' }),
    event({ id: 'all', allDay: true, time: '' }),
    event({ id: 'early', time: '08:00' })
  ], '2026-01-01', '2026-01-02');
  assert.deepEqual(Array.from(rows, row => row.id), ['all', 'early', 'later']);
});

test('invalid imported events are omitted with validation messages available', () => {
  assert(dates.validateEvent(event({ date: '2026-02-29' })).length);
  assert(dates.validateEvent(event({ time: '24:00' })).length);
  assert(dates.validateEvent(event({ repeat: 'hourly' })).length);
  assert(dates.validateEvent(event({ until: '2025-12-31' })).length);
  assert(dates.validateEvent(event({ exceptions: ['yesterday'] })).length);
  assert.deepEqual(Array.from(dates.expandEvents([null, event({ date: '2026-02-30' }), event()],
    '2026-01-01', '2026-01-02'), row => row.id), ['e']);
});

test('does not mutate seed models and supports very old series efficiently', () => {
  const seed = event({ date: '0001-01-01', repeat: 'daily' });
  const copy = JSON.stringify(seed);
  const rows = dates.expandEvents([seed, seed], '2026-10-31', '2026-11-01');
  assert.equal(rows.length, 2);
  assert.equal(JSON.stringify(seed), copy);
});

test('next occurrence is strictly after the requested date and honors recurrence bounds', () => {
  assert.equal(dates.nextOccurrence(event({ repeat: 'weekly' }), '2026-01-01'), '2026-01-08');
  assert.equal(dates.nextOccurrence(event({ repeat: 'daily', until: '2026-01-02' }),
    '2026-01-01'), '2026-01-02');
  assert.equal(dates.nextOccurrence(event({ repeat: 'daily', until: '2026-01-02' }),
    '2026-01-02'), null);
  assert.equal(dates.nextOccurrence(event({ date: '2026-01-31', repeat: 'monthly' }),
    '2026-01-31'), '2026-03-31');
  assert.equal(dates.nextOccurrence(event({ repeat: 'daily', exceptions: ['2026-01-02'] }),
    '2026-01-01'), '2026-01-03');
});

test('next occurrence finds leap birthdays across a non-leap century and handles a one-off', () => {
  assert.equal(dates.nextOccurrence(event({ date: '2096-02-29', repeat: 'yearly' }),
    '2096-03-01'), '2104-02-29');
  assert.equal(dates.nextOccurrence(event({ date: '2026-11-02' }), '2026-10-31'), '2026-11-02');
  assert.equal(dates.nextOccurrence(event({ date: '2026-11-02' }), '2026-11-02'), null);
  assert.equal(dates.nextOccurrence(event({ repeat: 'daily' }), '9999-12-31'), null);
  assert.equal(dates.nextOccurrence(event({ date: '2026-02-30' }), '2026-10-31'), null);
});
