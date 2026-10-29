import assert from 'node:assert/strict';
import test from 'node:test';
import { STAGES, STYLES, LENSES, SCENARIOS, getVariant, getLens, checkpointDirection, imaginedPerspective } from '../parenting-model.js';

test('all age-specific conversations have three moments and all five workbook exemplars', () => {
  assert.equal(Object.keys(STAGES).length, 5);
  assert.deepEqual(STYLES.map(s => s.level), [1,2,3,4,5]);
  for (const scenario of SCENARIOS) for (const [stage,variant] of Object.entries(scenario.variants)) {
    assert.ok(STAGES[stage]);
    assert.equal(variant.turns.length, 3, `${scenario.id}/${stage}`);
    for (const turn of variant.turns) {
      assert.equal(turn.choices.length, 5);
      assert.ok(turn.choices.every(text => typeof text === 'string' && text.length > 10));
      assert.ok(!/your (baby|child)/i.test([variant.intro,turn.speech,...turn.choices].join(' ')));
      assert.match(turn.choices[4], /hit|slap|smack|physical punishment|Threaten punishment/, `${scenario.id}/${stage}: level 5 must remain distinguishable from level 4`);
      const available = new Set(LENSES[getLens(stage)].factors.map(f => f.id));
      assert.ok(turn.focus.every(id => available.has(id)), `${scenario.id}/${stage}: unknown developmental factor`);
    }
  }
});

test('the five stages have distinct Erikson lenses without routing teens to toddler dialogue', () => {
  assert.equal(getLens('toddler'),'autonomy');
  assert.equal(getLens('preschool'),'initiative');
  assert.equal(getLens('teen'),'identity');
  assert.notDeepEqual(LENSES.trust.factors,LENSES.industry.factors);
  assert.notDeepEqual(LENSES.industry.factors,LENSES.identity.factors);
  assert.equal(getVariant(SCENARIOS[0],'infant'),null);
  assert.match(getVariant(SCENARIOS[0],'teen').turns[0].speech,/isn’t for me/);
  const named = getVariant(SCENARIOS.find(s=>s.id==='milk'),'infant','Alex');
  assert.match(named.intro,/Alex/);
  assert.ok(!named.turns.flatMap(t=>[t.speech,...t.choices]).join(' ').includes('Mia'));
});

test('unclassified and unshown areas never imply a developmental score', () => {
  for (const lens of Object.values(LENSES)) for (const factor of lens.factors) {
    assert.equal(checkpointDirection(null,factor.id).position,null);
    assert.equal(checkpointDirection('level1',factor.id,false).label,'Not shown');
    assert.equal(checkpointDirection('level5',factor.id).label,'Safety concern');
  }
  assert.match(imaginedPerspective(null,'identity'),/not interpreted/);
});
