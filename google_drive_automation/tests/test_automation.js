const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8')
  .replace('const USE_REFERENCE_SOURCE = true;', 'var USE_REFERENCE_SOURCE = false;')
  .replaceAll('YOUR_INPUT_FOLDER_ID_HERE', 'input')
  .replaceAll('YOUR_OUTPUT_FOLDER_ID_HERE', 'output')
  .replaceAll('YOUR_RENDER_APP_NAME', 'test')
  .replaceAll('YOUR_NEW_GEMINI_API_KEY_HERE', 'dummy')
  .replaceAll('YOUR_PRIVATE_JOB_TOKEN_HERE', 'private');

function iterator(items) {
  let index = 0;
  return {hasNext: () => index < items.length, next: () => items[index++]};
}
function fixture(text = 'large source') {
  let name = 'Course.docx', counter = 0, locked = false, now = 1000000;
  const state = {}, output = [], requests = [], logs = [];
  const input = {getId: () => 'input-file', getName: () => name,
    setName: n => {name = n;}, getMimeType: () => 'google-doc', isTrashed: () => false};
  const props = {getProperties: () => ({...state}), getProperty: k => state[k] || null,
    setProperty: (k, v) => {state[k] = v;}, deleteProperty: k => {delete state[k];}};
  const outputFolder = {getFilesByName: n => iterator(output.filter(f => f.getName() === n)),
    createFile: blob => {
      let fileName = blob.name;
      const file = {getId: () => 'out-' + output.length, getName: () => fileName,
        setName: n => {fileName = n;}, setDescription: () => {}};
      // Stable identity, independent of output array length after insertion.
      const id = 'out-' + output.length; file.getId = () => id;
      output.push(file); return file;
    }};
  function response(code, data) {
    return {getResponseCode: () => code, getContentText: () => JSON.stringify(data),
      getBlob: () => ({name: '', getBytes: () => [80, 75, 3, 4], setName(n) {this.name = n; return this;}})};
  }
  const f = {input, output, requests, logs, state, props, response, outputFolder,
    advance: ms => {now += ms;},
    handler: (url, options) => response(options.method === 'post' ? 202 : 200,
      {id: 'job-one', status: options.method === 'post' ? 'queued' : 'processing'})};
  const context = {
    Date: {now: () => now},
    Logger: {log: value => logs.push(value)}, MimeType: {GOOGLE_DOCS: 'google-doc'},
    PropertiesService: {getScriptProperties: () => props},
    LockService: {getScriptLock: () => ({tryLock: () => {if (locked) return false; locked = true; return true;},
      releaseLock: () => {locked = false;}})},
    DriveApp: {getFolderById: id => id === 'input' ? {getFiles: () => iterator([input])} : outputFolder,
      getFileById: id => id === 'input-file' ? input : output.find(o => o.getId() === id)},
    DocumentApp: {openById: () => ({getBody: () => ({getText: () => text})})},
    Utilities: {getUuid: () => 'request-' + ++counter, base64Encode: bytes => Buffer.from(bytes).toString('base64')},
    ScriptApp: {getOAuthToken: () => 'dummy-oauth-token'},
    UrlFetchApp: {fetch: (url, options) => {requests.push({url, options}); return f.handler(url, options);}}
  };
  vm.createContext(context); vm.runInContext(source, context);
  f.run = () => vm.runInContext('processNewCourseOutlines()', context);
  f.recover = () => vm.runInContext('recoverStuckFiles()', context);
  f.context = context;
  return f;
}

const tests = {
  'every fetch including Google export uses a bounded timeout'() {
    const f = fixture(); f.context.USE_REFERENCE_SOURCE = true;
    f.handler = (url, options) => url.includes('/export?') ? f.response(200, {}) : f.response(202, {id: 'job-one'});
    f.run(); f.run();
    for (const request of f.requests) assert.equal(request.options.timeoutSeconds, 60);
  },
  'source export consumes budget and shortens the submit timeout'() {
    const f = fixture(); f.context.USE_REFERENCE_SOURCE = true;
    f.handler = url => {if (url.includes('/export?')) {f.advance(70000); return f.response(200, {});}
      return f.response(202, {id: 'job-one'});};
    f.run();
    assert.equal(f.requests[1].options.timeoutSeconds, 35);
  },
  'fetch timeout preserves request identity and checkpoint for the next run'() {
    const f = fixture(); let calls = 0;
    f.handler = () => {if (++calls === 1) {f.advance(60000); throw new Error('request timeout');}
      return f.response(202, {id: 'job-one'});};
    f.run();
    const saved = JSON.parse(f.state.BTOOLS_JOB_input_file || f.state['BTOOLS_JOB_input-file']);
    assert.equal(saved.lastOperation, 'job_submit');
    f.run();
    assert.equal(JSON.parse(f.requests[1].options.payload).request_id, saved.requestId);
    assert.equal(f.input.getName(), '[PROCESSING]_Course.docx');
  },
  'audit download near deadline defers result and resumes without duplicate audit'() {
    const f = fixture(); f.run();
    f.handler = url => {
      if (url.endsWith('/audit')) {f.advance(104000); return f.response(200, {});}
      return /\/result$/.test(url) ? f.response(200, {}) :
        f.response(200, {status: 'succeeded', filename: 'Test.docx', audit_available: true});
    };
    f.run();
    assert.equal(f.output.length, 1);
    assert.equal(f.requests.filter(r => r.url.endsWith('/result')).length, 0);
    assert.ok(JSON.parse(f.state['BTOOLS_JOB_input-file']).auditFileId);
    f.run();
    assert.equal(f.output.length, 2);
    assert.equal(f.requests.filter(r => r.url.endsWith('/audit')).length, 1);
    assert.equal(f.input.getName(), '[DONE]_Course.docx');
  },
  'new Google Docs path exports DOCX and sends binary source instead of flattened text'() {
    const f = fixture(); f.context.USE_REFERENCE_SOURCE = true;
    f.handler = (url, options) => url.includes('/export?') ? f.response(200, {}) : f.response(202, {id: 'job-one', status: 'queued'});
    f.run();
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[0].options.headers.Authorization, 'Bearer dummy-oauth-token');
    const sent = JSON.parse(f.requests[1].options.payload);
    assert.equal(sent.source_docx_base64, 'UEsDBA==');
    assert.equal(sent.raw_text, undefined);
  },
  'review result saves audit and marks REVIEW without reprocessing'() {
    const f = fixture(); f.run();
    f.handler = url => /\/(result|audit)$/.test(url) ? f.response(200, {}) :
      f.response(200, {status: 'succeeded', filename: 'B Tools_Test.docx', audit_available: true, review_required: true});
    f.run(); f.run();
    assert.equal(f.output.length, 2);
    assert.equal(f.input.getName(), '[REVIEW]_Course.docx');
    assert.equal(f.output.filter(o => o.getName().endsWith('.review.json')).length, 1);
    assert.equal(f.requests.filter(r => r.options.method === 'post').length, 1);
  },
  'audit save interrupted before state update recovers without duplicate report'() {
    const f = fixture(); f.run();
    f.handler = url => /\/(result|audit)$/.test(url) ? f.response(200, {}) :
      f.response(200, {status: 'succeeded', filename: 'B Tools_Test.docx', audit_available: true, review_required: true});
    const save = f.props.setProperty;
    f.props.setProperty = (k, value) => {if (JSON.parse(value).auditFileId) throw new Error('stop after audit creation'); save(k, value);};
    f.run(); assert.equal(f.output.length, 1);
    f.props.setProperty = save; f.run();
    assert.equal(f.output.length, 2);
    assert.equal(f.input.getName(), '[REVIEW]_Course.docx');
  },
  'long job is submitted once and polled on later runs'() {
    const f = fixture('large text '.repeat(10000));
    f.run(); f.run(); f.run();
    assert.equal(f.requests.filter(r => r.options.method === 'post').length, 1);
    assert.equal(f.requests.filter(r => r.options.method === 'get').length, 2);
    assert.equal(f.output.length, 0);
    assert.equal(f.input.getName(), '[PROCESSING]_Course.docx');
  },
  'success creates one output and clears processing state'() {
    const f = fixture(); f.run();
    f.handler = url => url.endsWith('/result') ? f.response(200, {}) :
      f.response(200, {status: 'succeeded', filename: 'B Tools_Test.docx', model: 'mock'});
    f.run(); f.run();
    assert.equal(f.output.length, 1);
    assert.equal(f.output[0].getName(), 'B Tools_Test.docx');
    assert.equal(f.input.getName(), '[DONE]_Course.docx');
    assert.deepEqual(f.state, {});
  },
  'lost submit response reuses the saved request id'() {
    const f = fixture(); let attempts = 0;
    f.handler = () => {if (++attempts === 1) throw new Error('network response lost');
      return f.response(202, {id: 'job-one', status: 'processing'});};
    f.run(); f.run();
    assert.equal(f.requests.length, 2);
    assert.equal(JSON.parse(f.requests[0].options.payload).request_id,
                 JSON.parse(f.requests[1].options.payload).request_id);
    assert.equal(JSON.parse(f.state['BTOOLS_JOB_input-file']).jobId, 'job-one');
  },
  'server restart missing job triggers a new bounded retry'() {
    const f = fixture(); f.run();
    f.handler = (url, options) => options.method === 'post' ?
      f.response(202, {id: 'new-job', status: 'queued'}) : f.response(404, {});
    f.run();
    assert.equal(f.input.getName(), '[PROCESSING]_[RETRY_1]_Course.docx');
    assert.equal(JSON.parse(f.state['BTOOLS_JOB_input-file']).jobId, 'new-job');
  },
  'empty source is skipped and never remains processing'() {
    const f = fixture(''); f.run();
    assert.equal(f.input.getName(), '[SKIP]_Course.docx');
    assert.equal(f.requests.length, 0);
    assert.deepEqual(f.state, {});
  },
  'legacy recovery ignores jobs with active state'() {
    const f = fixture(); f.input.setName('[PROCESSING]_old.docx'); f.recover();
    assert.equal(f.input.getName(), 'old.docx');
    f.run(); f.recover();
    assert.equal(f.input.getName(), '[PROCESSING]_old.docx');
  },
  'crash after saving output recovers marker file without duplication'() {
    const f = fixture(); f.run();
    f.handler = url => url.endsWith('/result') ? f.response(200, {}) :
      f.response(200, {status: 'succeeded', filename: 'B Tools_Test.docx'});
    const save = f.props.setProperty;
    f.props.setProperty = (k, value) => {
      if (JSON.parse(value).outputFileId) throw new Error('hard stop after createFile');
      save(k, value);
    };
    f.run();
    assert.equal(f.output.length, 1);
    assert.equal(f.output[0].getName(), '__BTOOLS_JOB_job-one.docx');
    f.props.setProperty = save;
    f.run();
    assert.equal(f.output.length, 1);
    assert.equal(f.input.getName(), '[DONE]_Course.docx');
  },
  'retry exhaustion produces SKIP'() {
    const f = fixture();
    f.context.testFile = f.input;
    vm.runInContext("handleRetryRename(testFile, '[RETRY_3]_Course.docx')", f.context);
    assert.equal(f.input.getName(), '[SKIP]_Course.docx');
  }
};
for (const [name, test] of Object.entries(tests)) {
  test(); console.log('PASS ' + name);
}
console.log(Object.keys(tests).length + ' automation tests passed');
