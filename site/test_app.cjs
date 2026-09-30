'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

function mount(hash = '') {
  const events = {};
  const titles = ['One family', 'Another family'];
  const families = titles.map((title, index) => ({
    id: `family-${index}`, hidden: false,
    querySelector() { return {textContent: title, focus: () => { this.focused = true; }}; },
    scrollIntoView() { this.scrolled = true; },
  }));
  const links = families.map(family => ({
    hash: `#${family.id}`, attributes: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    removeAttribute(key) { delete this.attributes[key]; },
  }));
  const status = {textContent: ''};
  const location = {hash};
  const document = {
    querySelectorAll(selector) { return selector === '.family' ? families : links; },
    getElementById(id) { return id === 'selection-status' ? status : families.find(f => f.id === id); },
    addEventListener(type, handler) { events[type] = handler; },
  };
  const window = {addEventListener(type, handler) { events[type] = handler; }};
  const history = {pushState(_state, _title, nextHash) { location.hash = nextHash; }};
  vm.runInNewContext(source, {document, window, location, history, matchMedia: () => ({matches: true})});
  function click(index, modifiers = {}) {
    const event = {target: {closest() { return links[index]; }}, preventDefault() { this.prevented = true; }, ...modifiers};
    events.click(event);
    return event;
  }
  return {families, links, status, location, events, click};
}

test('initial state selects exactly the first family', () => {
  const app = mount();
  assert.deepEqual(app.families.map(f => f.hidden), [false, true]);
  assert.equal(app.links[0].attributes['aria-current'], 'true');
  assert.equal(app.status.textContent, '');
});

test('deep links select the requested family', () => {
  const app = mount('#family-1');
  assert.deepEqual(app.families.map(f => f.hidden), [true, false]);
  assert.equal(app.links[1].attributes['aria-current'], 'true');
});

test('family click updates history, keyboard focus and announcement', () => {
  const app = mount();
  assert.equal(app.click(1).prevented, true);
  assert.equal(app.location.hash, '#family-1');
  assert.equal(app.families[1].focused, true);
  assert.equal(app.families[1].scrolled, true);
  assert.equal(app.status.textContent, 'Selected example: Another family');
  assert.equal(app.links[0].attributes['aria-current'], undefined);
});

test('browser navigation restores the appropriate selected family', () => {
  const app = mount();
  app.click(1);
  app.location.hash = '#family-0';
  app.events.popstate();
  assert.deepEqual(app.families.map(f => f.hidden), [false, true]);
});

test('benchmark and unknown hashes preserve the current family', () => {
  const app = mount('#family-1');
  app.location.hash = '#benchmark';
  app.events.hashchange();
  assert.deepEqual(app.families.map(f => f.hidden), [true, false]);
});

test('modifier clicks preserve normal browser behavior', () => {
  const app = mount();
  assert.equal(app.click(1, {ctrlKey: true}).prevented, undefined);
  assert.deepEqual(app.families.map(f => f.hidden), [false, true]);
});
