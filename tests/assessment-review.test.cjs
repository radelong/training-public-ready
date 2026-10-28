const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('saved assessment results can be reviewed from learner and admin tables', async () => {
  const source = fs.readFileSync('frontend/academy.js', 'utf8');
  const render = source.slice(source.indexOf('async function reviewAssessment('),
                              source.indexOf('function renderAssessmentAttempt('));
  const detail = source.slice(source.indexOf('function renderAssessmentAttempt('),
                              source.indexOf('async function saveAssessmentProgress('));
  const results = source.slice(source.indexOf('async function loadAcademyAssessmentResults('),
                               source.indexOf('function renderAccount('));
  assert.ok(render && detail && results);
  assert.match(source, /target\.dataset\.assessmentReview\)await reviewAssessment/);
  const completed = {id: 'attempt-1', kind: 'overall', status: 'graded', score: 75,
    passed: null, submitted: 1, created: 1, area_scores: {Linux: {score: 75}}};
  const active = {...completed, id: 'attempt-2', status: 'in_progress'};
  const catalog = {assessments: {overall: {question_count: 80}, graduation: {question_count: 80}},
    attempts: [active, completed]};
  const elements = {content: {}, 'academy-assessment-results': {}};
  const state = {user: {role: 'admin'}, assessment: null, assessmentIndex: null};
  const calls = [];
  let description = '';
  const context = vm.createContext({state, Object, encodeURIComponent,
    $: id => elements[id], esc: value => String(value), date: value => `date-${value}`,
    heading: (title, value) => {description = value; return '';}, page: async name => calls.push(['page', name]),
    api: async url => {calls.push(['api', url]);
      if (url === '/academy-assessments') return catalog;
      if (url === '/admin/academy-assessment-results') return [{...completed, username: 'learner'}, active];
      if (url === '/academy-assessments/attempts/attempt-1') return completed;
      if (url === '/academy-assessments/attempts/attempt-2') return active;
      throw new Error(`Unexpected API request ${url}`);
    }});
  vm.runInContext(render + '\n' + detail + '\n' + results, context);
  await vm.runInContext('renderAssessments({showCatalog:true})', context);
  assert.equal((elements.content.innerHTML.match(/data-assessment-review="attempt-1"/g) || []).length, 2);
  assert.doesNotMatch(elements.content.innerHTML, /data-assessment-review="attempt-2"/);
  await vm.runInContext('loadAcademyAssessmentResults()', context);
  assert.match(elements['academy-assessment-results'].innerHTML, /data-assessment-review="attempt-1"/);
  await vm.runInContext("reviewAssessment('attempt-1')", context);
  assert.equal(state.assessment.id, 'attempt-1');
  assert.deepEqual(calls.at(-1), ['page', 'assessments']);
  await assert.rejects(vm.runInContext("reviewAssessment('attempt-2')", context), /not ready for review/);
  vm.runInContext("renderAssessmentAttempt({kind:'overall',status:'graded',username:'learner',questions:[],area_scores:{},recommendations:[],answers:{},correct_answers:{},submitted:1,score:75})", context);
  assert.equal(description, 'Result for learner.');
});
