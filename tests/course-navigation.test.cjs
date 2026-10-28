const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function openSavedCourse(completed) {
  const lesson = {id: 'course-1', current_module: 'module3', completed,
    progress_test_attempt: null, pretest_available: false,
    content: {progress_test_enabled: false, modules: [
      {id: 'module1', required: true}, {id: 'module2', required: true},
      {id: 'module3', required: true}]}};
  const calls = [];
  const context = vm.createContext({document: {addEventListener() {}}, window: {},
    state: {}, api: async (url, method) => {calls.push([url, method]); return method === 'POST' ? {} : lesson;}});
  vm.runInContext(fs.readFileSync('frontend/learning.js', 'utf8') + '\nrenderLesson=()=>{};', context);
  await vm.runInContext("openCourse('course-1')", context);
  return {index: vm.runInContext('learning.module', context), calls};
}

test('opening an older saved position returns to the first unfinished required module', async () => {
  assert.equal((await openSavedCourse([])).index, 0);
  assert.equal((await openSavedCourse(['module1'])).index, 1);
  assert.equal((await openSavedCourse(['module1', 'module2'])).index, 2);
  assert.equal((await openSavedCourse([])).calls.some(([, method]) => method === 'PUT'), false);
});
