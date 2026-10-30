import assert from 'node:assert/strict';
import test from 'node:test';
import { SCENARIOS, STAGES, STYLES, LENSES, getLens } from '../parenting-model.js';
import { SCENE_INFO, STAGE_INFO } from '../scene-content.js';

const BANNED = /\b(hit|smack|slap|hurt|bleed|bruise)/i;
const nonEmpty = s => typeof s === 'string' && s.trim().length > 0;
const checkReplies = (row, where) => {
  assert.equal(row.length, STYLES.length, where);
  for (const r of row) {
    assert.ok(nonEmpty(r), where);
    assert.ok(!BANNED.test(r), `${where}: banned word in reply “${r}”`);
  }
};

test('every stage has plain-language stage info', () => {
  for (const stage of Object.keys(STAGES)) {
    const info = STAGE_INFO[stage];
    assert.ok(info, stage);
    for (const key of ['short','ages','icon','blurb']) assert.ok(nonEmpty(info[key]), `${stage}.${key}`);
  }
});

test('every existing variant has scene info with 3×5 replies', () => {
  let count = 0;
  for (const scenario of SCENARIOS) for (const [stage, variant] of Object.entries(scenario.variants)) {
    const where = `${scenario.id}/${stage}`;
    const info = SCENE_INFO[scenario.id]?.[stage];
    assert.ok(info, `${where}: missing SCENE_INFO`);
    for (const key of ['summary','need','skill']) assert.ok(nonEmpty(info[key]), `${where}.${key}`);
    assert.ok(info.beats.length >= 2 && info.beats.length <= 3, `${where}: 2–3 beats`);
    for (const b of info.beats) {
      assert.ok(nonEmpty(b), where);
      assert.ok(!BANNED.test(b), `${where}: banned word in beat “${b}”`);
    }
    assert.equal(info.replies.length, variant.turns.length, where);
    assert.equal(info.replies.length, 3, where);
    info.replies.forEach((row, t) => checkReplies(row, `${where} turn ${t + 1}`));
    count++;
  }
  assert.equal(count, 23);
});

test('scene info has no entries for variants that do not exist', () => {
  for (const [id, stages] of Object.entries(SCENE_INFO)) {
    const scenario = SCENARIOS.find(s => s.id === id);
    assert.ok(scenario, id);
    for (const stage of Object.keys(stages)) assert.ok(scenario.variants[stage], `${id}/${stage}`);
  }
});

test('extra turns, when present, follow the turn conventions', () => {
  let found = 0;
  for (const [id, stages] of Object.entries(SCENE_INFO)) for (const [stage, info] of Object.entries(stages)) {
    if (!info.extraTurns) continue;
    found++;
    const where = `${id}/${stage} extra`;
    const available = new Set(LENSES[getLens(stage)].factors.map(f => f.id));
    assert.equal(info.extraTurns.length, 2, where);
    info.extraTurns.forEach((turn, i) => {
      const w = `${where} ${i + 1}`;
      assert.ok(nonEmpty(turn.speech), w);
      assert.equal(turn.choices.length, 5, w);
      assert.ok(turn.choices.every(c => nonEmpty(c) && c.length > 10), w);
      assert.match(turn.choices[4], /hit|slap|smack|physical punishment|Threaten punishment/, `${w}: level 5 must stay distinguishable`);
      assert.ok(turn.focus.length >= 3 && turn.focus.length <= 5, `${w}: 3–5 focus ids`);
      assert.ok(turn.focus.every(f => available.has(f)), `${w}: unknown factor`);
      checkReplies(turn.replies, w);
    });
  }
  assert.equal(found, 4);
  for (const [id, stage] of [['bed','infant'],['milk','toddler'],['bed','school'],['bed','teen']]) assert.ok(SCENE_INFO[id][stage].extraTurns, `${id}/${stage}`);
});
