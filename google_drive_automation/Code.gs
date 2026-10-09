/** Submit quickly; collect completed documents on later trigger runs. */
const INPUT_FOLDER_ID = "YOUR_INPUT_FOLDER_ID_HERE";
const OUTPUT_FOLDER_ID = "YOUR_OUTPUT_FOLDER_ID_HERE";
// An existing URL ending in /api/format_text is also accepted.
const RENDER_API_URL = "https://YOUR_RENDER_APP_NAME.onrender.com";
const GEMINI_API_KEY = "YOUR_NEW_GEMINI_API_KEY_HERE";
// Set the same private value as BTOOLS_API_TOKEN in Render Environment.
const BTOOLS_API_TOKEN = "YOUR_PRIVATE_JOB_TOKEN_HERE";
const RUN_BUDGET_MS = 120000;
const HTTP_TIMEOUT_SECONDS = 60;
const RUN_RESERVE_MS = 15000;
var runDeadlineMs = 0;
const MAX_NEW_FILES = 1;
const MAX_ACTIVE_FILES = 2;
const MAX_JOB_WAIT_MS = 90 * 60 * 1000;
const JOB_PROPERTY_PREFIX = "BTOOLS_JOB_";
// Set false only while using the original server before installing this update.
const USE_REFERENCE_SOURCE = true;

function cleanFolderId(idStr) {
  return idStr ? idStr.trim().split('/folders/').pop().split('?')[0].split('/')[0].trim() : '';
}
function apiBaseUrl() {
  return RENDER_API_URL.replace(/\/+$/, '').replace(/\/api\/(format_text|jobs)$/, '');
}
function boundedFetch(url, options, operation) {
  var remaining = runDeadlineMs ? runDeadlineMs - Date.now() - RUN_RESERVE_MS : RUN_BUDGET_MS - RUN_RESERVE_MS;
  var seconds = Math.min(HTTP_TIMEOUT_SECONDS, Math.floor(remaining / 1000));
  if (seconds < 5) throw new Error('BTOOLS_DEFER: รอทำต่อรอบถัดไป');
  options.timeoutSeconds = seconds;
  var started = Date.now();
  Logger.log('HTTP start | ' + operation + ' | timeoutSeconds=' + seconds);
  try {
    var response = UrlFetchApp.fetch(url, options);
    Logger.log('HTTP end | ' + operation + ' | status=' + response.getResponseCode() + ' | elapsedMs=' + (Date.now() - started));
    return response;
  } catch (e) {
    Logger.log('HTTP interrupted | ' + operation + ' | elapsedMs=' + (Date.now() - started));
    throw e;
  }
}
function checkpoint(file, state, operation) {
  state.lastOperation = operation;
  state.lastOperationAt = Date.now();
  saveState(file.getId(), state);
}
function jobRequest(path, payload) {
  var options = {method: payload ? 'post' : 'get',
    headers: {'X-BTools-Token': BTOOLS_API_TOKEN}, muteHttpExceptions: true};
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  return boundedFetch(apiBaseUrl() + path, options,
    payload ? 'job_submit' : (path.endsWith('/audit') ? 'job_audit' : (path.endsWith('/result') ? 'job_result' : 'job_status')));
}
function extractTextFromDocxBlob(blob) {
  var parts = Utilities.unzip(blob.setContentType('application/zip'));
  for (var i = 0; i < parts.length; i++) {
    if (parts[i].getName() !== 'word/document.xml') continue;
    // Preserve paragraphs across font runs and decode XML entities.
    var xml = XmlService.parse(parts[i].getDataAsString());
    var ns = XmlService.getNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main');
    var paragraphs = [];
    function collectText(element) {
      if (element.getNamespace().getURI() === ns.getURI()) {
        if (element.getName() === 't') return element.getText();
        if (element.getName() === 'tab') return '\t';
        if (element.getName() === 'br') return '\n';
      }
      return element.getChildren().map(collectText).join('');
    }
    function walk(element) {
      if (element.getName() === 'p' && element.getNamespace().getURI() === ns.getURI()) {
        var text = collectText(element);
        if (text.trim()) paragraphs.push(text);
      } else { element.getChildren().forEach(walk); }
    }
    walk(xml.getRootElement());
    return paragraphs.join('\n');
  }
  return '';
}
function readSourceText(file) {
  if (file.getMimeType() === MimeType.GOOGLE_DOCS) return DocumentApp.openById(file.getId()).getBody().getText();
  return extractTextFromDocxBlob(file.getBlob());
}
function readSourcePayload(file) {
  if (!USE_REFERENCE_SOURCE) return {raw_text: readSourceText(file)};
  var blob;
  if (file.getMimeType() === MimeType.GOOGLE_DOCS) {
    var response = boundedFetch('https://www.googleapis.com/drive/v3/files/' +
      encodeURIComponent(file.getId()) + '/export?mimeType=' +
      encodeURIComponent('application/vnd.openxmlformats-officedocument.wordprocessingml.document'), {
        headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()}, muteHttpExceptions: true}, 'source_export');
    if (response.getResponseCode() !== 200) throw new Error('Export Google Doc HTTP ' + response.getResponseCode());
    blob = response.getBlob();
  } else {
    var mime = file.getMimeType();
    if (mime !== 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' && !/\.docx$/i.test(file.getName())) {
      throw new Error('รองรับเฉพาะ Google Docs และ .docx');
    }
    blob = file.getBlob();
  }
  var bytes = blob.getBytes();
  if (bytes.length > 20 * 1024 * 1024) throw new Error('ต้นฉบับเกินขนาด 20 MB');
  return {source_docx_base64: Utilities.base64Encode(bytes)};
}
function saveState(fileId, state) {
  PropertiesService.getScriptProperties().setProperty(JOB_PROPERTY_PREFIX + fileId, JSON.stringify(state));
}
function deleteState(fileId) {
  PropertiesService.getScriptProperties().deleteProperty(JOB_PROPERTY_PREFIX + fileId);
}
function retryFile(file, state, reason) {
  Logger.log('ลองใหม่: ' + state.originalName + ' — ' + reason);
  handleRetryRename(file, state.originalName);
  deleteState(file.getId());
}
function submitFile(file, state) {
  checkpoint(file, state, 'source_read');
  var payload = readSourcePayload(file);
  if (payload.raw_text !== undefined && !payload.raw_text.trim()) {
    file.setName('[SKIP]_' + state.originalName.replace(/^\[RETRY_\d+\]_/, ''));
    deleteState(file.getId());
    Logger.log('ไฟล์ว่างหรืออ่านเนื้อหาไม่ได้: ' + state.originalName);
    return;
  }
  payload.api_key = GEMINI_API_KEY;
  payload.request_id = state.requestId;
  checkpoint(file, state, 'job_submit');
  var response = jobRequest('/api/jobs', payload);
  var code = response.getResponseCode();
  if (code === 202) {
    var job = JSON.parse(response.getContentText());
    if (!job.id) throw new Error('Render returned no job id');
    state.jobId = job.id;
    saveState(file.getId(), state);
    file.setName('[PROCESSING]_' + state.originalName);
    Logger.log('รับงานแล้ว: ' + state.originalName + ' | Job ' + job.id + ' | ' + job.status);
  } else if (code === 401 || code === 403 || code === 503) {
    throw new Error('ตรวจ BTOOLS_API_TOKEN และการตั้งค่า Render (HTTP ' + code + ')');
  } else if (code === 429 || code >= 500) {
    // Keep requestId: the response might have been lost after acceptance.
    Logger.log('Render ยังไม่พร้อมรับงาน รอรอบถัดไป (HTTP ' + code + ')');
  } else { retryFile(file, state, 'รับงานไม่สำเร็จ HTTP ' + code); }
}
function finishFile(file, state, outputFolder, job) {
  state.reviewRequired = state.reviewRequired || !!job.review_required;
  state.auditRequired = state.auditRequired || !!job.audit_available;
  state.filename = job.filename || state.filename || 'B Tools_Course_Outline.docx';
  saveState(file.getId(), state);
  if (state.auditRequired) {
    var auditMarker = '__BTOOLS_JOB_' + state.jobId + '.review.json';
    var auditFile = state.auditFileId ? DriveApp.getFileById(state.auditFileId) : null;
    if (!auditFile) {
      checkpoint(file, state, 'job_audit');
      var auditMatches = outputFolder.getFilesByName(auditMarker);
      if (auditMatches.hasNext()) auditFile = auditMatches.next();
    }
    if (!auditFile) {
      var auditResponse = jobRequest('/api/jobs/' + encodeURIComponent(state.jobId) + '/audit');
      if (auditResponse.getResponseCode() !== 200) throw new Error('ดาวน์โหลดรายงานตรวจสอบ HTTP ' + auditResponse.getResponseCode());
      auditFile = outputFolder.createFile(auditResponse.getBlob().setName(auditMarker));
    }
    state.auditFileId = auditFile.getId();
    saveState(file.getId(), state);
    auditFile.setName(state.filename.replace(/\.docx$/i, '') + '.review.json');
  }
  var markerName = '__BTOOLS_JOB_' + state.jobId + '.docx';
  var outputFile = state.outputFileId ? DriveApp.getFileById(state.outputFileId) : null;
  if (!outputFile) {
    checkpoint(file, state, 'job_result');
    // Recover a file created just before a hard timeout, without saving twice.
    var matches = outputFolder.getFilesByName(markerName);
    if (matches.hasNext()) outputFile = matches.next();
  }
  if (!outputFile) {
    var response = jobRequest('/api/jobs/' + encodeURIComponent(state.jobId) + '/result');
    if (response.getResponseCode() === 404) {
      retryFile(file, state, 'ผลลัพธ์หายหลังเซิร์ฟเวอร์รีสตาร์ต');
      return;
    }
    if (response.getResponseCode() !== 200) throw new Error('ดาวน์โหลดผลลัพธ์ HTTP ' + response.getResponseCode());
    outputFile = outputFolder.createFile(response.getBlob().setName(markerName));
  }
  state.outputFileId = outputFile.getId();
  saveState(file.getId(), state); // Persist identity BEFORE renaming output.
  outputFile.setName(state.filename);
  outputFile.setDescription('B Tools job: ' + state.jobId + ' | Source: ' + file.getId() +
    (state.reviewRequired ? ' | REVIEW REQUIRED: ตรวจรายงานท้ายเอกสารและ .review.json' : ''));
  file.setName((state.reviewRequired ? '[REVIEW]_' : '[DONE]_') + state.originalName.replace(/^\[RETRY_\d+\]_/, ''));
  deleteState(file.getId());
  Logger.log('บันทึกสำเร็จ: ' + state.filename + ' | ' + (job.model || 'unknown'));
}
function checkFile(file, state, outputFolder) {
  if (state.outputFileId) { finishFile(file, state, outputFolder, {filename: state.filename}); return; }
  if (!state.jobId) {
    if (Date.now() - state.startedAt > MAX_JOB_WAIT_MS) retryFile(file, state, 'ส่งงานไม่สำเร็จภายในเวลาที่กำหนด');
    else submitFile(file, state); // Same requestId prevents duplicate work.
    return;
  }
  checkpoint(file, state, 'job_status');
  var response = jobRequest('/api/jobs/' + encodeURIComponent(state.jobId));
  var code = response.getResponseCode();
  if (code === 404) { retryFile(file, state, 'เซิร์ฟเวอร์ไม่พบงานเดิม'); return; }
  if (code !== 200) throw new Error('ตรวจสถานะ HTTP ' + code);
  var job = JSON.parse(response.getContentText());
  if (job.status === 'succeeded') finishFile(file, state, outputFolder, job);
  else if (job.status === 'failed') retryFile(file, state, job.error || 'ประมวลผลไม่สำเร็จ');
  else if (Date.now() - state.startedAt > MAX_JOB_WAIT_MS) {
    // Do not resubmit a job still running, which would duplicate API work.
    Logger.log('งานรอนานผิดปกติ กรุณาตรวจ Render: ' + state.originalName + ' | ' + state.jobId);
  } else Logger.log('ยังทำงานอยู่: ' + state.originalName + ' | ' + job.status);
}
function processNewCourseOutlines() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return Logger.log('รอบก่อนยังทำงานอยู่ ข้ามรอบนี้');
  var started = Date.now();
  runDeadlineMs = started + RUN_BUDGET_MS;
  try {
    var inputId = cleanFolderId(INPUT_FOLDER_ID), outputId = cleanFolderId(OUTPUT_FOLDER_ID);
    if (!inputId || !outputId || inputId.indexOf('YOUR_') === 0 || outputId.indexOf('YOUR_') === 0 ||
        RENDER_API_URL.indexOf('YOUR_') !== -1 || !BTOOLS_API_TOKEN || BTOOLS_API_TOKEN.indexOf('YOUR_') === 0 ||
        !GEMINI_API_KEY || GEMINI_API_KEY.indexOf('YOUR_') === 0) {
      Logger.log('กรุณาตั้งค่า Folder IDs, RENDER_API_URL, GEMINI_API_KEY และ BTOOLS_API_TOKEN');
      return;
    }
    var inputFolder = DriveApp.getFolderById(inputId), outputFolder = DriveApp.getFolderById(outputId);
    var properties = PropertiesService.getScriptProperties(), states = properties.getProperties();
    var activeIds = Object.keys(states).filter(function(key) { return key.indexOf(JOB_PROPERTY_PREFIX) === 0; });
    // Collect finished work BEFORE accepting new input. State survives timeouts.
    for (var i = 0; i < activeIds.length; i++) {
      if (Date.now() - started >= RUN_BUDGET_MS) return;
      var fileId = activeIds[i].slice(JOB_PROPERTY_PREFIX.length);
      try {
        var file = DriveApp.getFileById(fileId);
        if (file.isTrashed()) { deleteState(fileId); continue; }
        checkFile(file, JSON.parse(states[activeIds[i]]), outputFolder);
      } catch (e) { Logger.log('ตรวจงานยังไม่สำเร็จ จะตรวจใหม่รอบหน้า: ' + e.toString()); }
    }
    var activeCount = Object.keys(properties.getProperties()).filter(function(key) {
      return key.indexOf(JOB_PROPERTY_PREFIX) === 0;
    }).length;
    var files = inputFolder.getFiles(), submitted = 0;
    while (files.hasNext() && submitted < MAX_NEW_FILES && activeCount < MAX_ACTIVE_FILES) {
      if (Date.now() - started >= RUN_BUDGET_MS) break;
      var file = files.next(), name = file.getName();
      if (properties.getProperty(JOB_PROPERTY_PREFIX + file.getId()) || /^\[(DONE|SKIP|PROCESSING|REVIEW)\]_/.test(name)) continue;
      if (file.getMimeType() !== MimeType.GOOGLE_DOCS && !/\.docx$/i.test(name)) continue;
      var state = {originalName: name, requestId: Utilities.getUuid(), startedAt: Date.now()};
      saveState(file.getId(), state); // BEFORE rename, extraction, and HTTP.
      activeCount++;
      submitted++;
      try {
        file.setName('[PROCESSING]_' + name);
        submitFile(file, state);
      } catch (e) { Logger.log('ส่งงานยังไม่สำเร็จ เก็บรหัสเดิมไว้ลองใหม่: ' + e.toString()); }
    }
  } finally { runDeadlineMs = 0; lock.releaseLock(); }
}
/** Run once AFTER both updates to recover old orphaned PROCESSING files. */
function recoverStuckFiles() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return Logger.log('รอบอื่นกำลังทำงานอยู่ ลองใหม่ภายหลัง');
  try {
    var files = DriveApp.getFolderById(cleanFolderId(INPUT_FOLDER_ID)).getFiles();
    var properties = PropertiesService.getScriptProperties(), count = 0;
    while (files.hasNext()) {
      var file = files.next(), name = file.getName();
      if (name.indexOf('[PROCESSING]_') === 0 && !properties.getProperty(JOB_PROPERTY_PREFIX + file.getId())) {
        file.setName(name.slice('[PROCESSING]_'.length));
        count++;
      }
    }
    Logger.log('คืนสถานะไฟล์ค้างเดิม ' + count + ' ไฟล์แล้ว');
  } finally { lock.releaseLock(); }
}
function handleRetryRename(file, originalName) {
  var match = originalName.match(/^\[RETRY_(\d+)\]_(.*)$/);
  var count = match ? parseInt(match[1], 10) + 1 : 1, name = match ? match[2] : originalName;
  file.setName(count > 3 ? '[SKIP]_' + name : '[RETRY_' + count + ']_' + name);
}
