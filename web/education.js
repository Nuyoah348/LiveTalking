const $ = id => document.getElementById(id);
let pc = null;
let sessionid = null;
let recording = false;
let connectionState = 'idle';

function notice(message, tone = 'info') {
  $('notice').textContent = message;
  $('notice').className = 'notice ' + tone;
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`服务端返回了非 JSON 响应（HTTP ${response.status}）`); }
  if (!response.ok || (typeof data.code === 'number' && data.code !== 0)) {
    throw new Error(data.msg || `请求失败（HTTP ${response.status}）`);
  }
  return data;
}

function jsonPost(url, data) {
  return requestJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
}

function setConnectionState(state) {
  connectionState = state;
  const connected = state === 'connected';
  $('statusBadge').classList.toggle('connected', connected);
  $('statusBadge').textContent = connected ? '已连接' : state === 'connecting' ? '连接中' : '未连接';
  $('connectionTitle').textContent = connected ? '数字人已就绪' : state === 'connecting' ? '正在建立连接…' : '准备好开始交流了吗？';
  $('btnStart').hidden = state !== 'idle';
  $('btnStop').hidden = state === 'idle';
  ['btnSend', 'btnUpload', 'btnInterrupt', 'btnSpeaking', 'btnRecToggle', 'btnAudiotype'].forEach(id => {
    $(id).disabled = !connected;
  });
}

function resetConnection() {
  const oldConnection = pc;
  pc = null;
  if (oldConnection) oldConnection.close();
  sessionid = null;
  recording = false;
  $('sessionIdDisplay').textContent = '请先连接数字人服务';
  $('video').srcObject = null;
  $('audio').srcObject = null;
  $('video').hidden = true;
  $('teacherPreview').hidden = false;
  $('stageTag').textContent = '形象预览';
  $('stageTag').classList.remove('live');
  $('avatarDisplay').textContent = '连接后显示服务端数字人';
  $('previewCaption').hidden = false;
  $('btnRecToggle').textContent = '开始录制';
  $('btnDownload').disabled = true;
  setConnectionState('idle');
}

async function waitForIce(connection) {
  if (connection.iceGatheringState === 'complete') return;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { cleanup(); reject(new Error('ICE 收集超时，请检查网络后重试')); }, 12000);
    function onChange() {
      if (connection.iceGatheringState === 'complete') { cleanup(); resolve(); }
    }
    function cleanup() {
      clearTimeout(timeout);
      connection.removeEventListener('icegatheringstatechange', onChange);
    }
    connection.addEventListener('icegatheringstatechange', onChange);
  });
}

async function start() {
  if (connectionState !== 'idle') return;
  setConnectionState('connecting');
  notice('正在连接数字人服务…');
  try {
    const connection = new RTCPeerConnection();
    pc = connection;
    connection.addTransceiver('video', { direction: 'recvonly' });
    connection.addTransceiver('audio', { direction: 'recvonly' });
    connection.addEventListener('track', event => {
      if (pc !== connection) return;
      if (event.track.kind === 'video') {
        $('video').srcObject = event.streams[0];
        $('video').hidden = false;
        $('teacherPreview').hidden = true;
        $('stageTag').textContent = '实时数字人';
        $('stageTag').classList.add('live');
        $('previewCaption').hidden = true;
      } else {
        $('audio').srcObject = event.streams[0];
      }
    });
    connection.addEventListener('connectionstatechange', () => {
      if (pc !== connection) return;
      if (connection.connectionState === 'connected') {
        setConnectionState('connected');
        notice('连接成功，可以开始交流。', 'success');
      } else if (['failed', 'disconnected', 'closed'].includes(connection.connectionState)) {
        resetConnection();
        notice('连接已中断，请重新连接。', 'error');
      }
    });
    const offer = await connection.createOffer();
    await connection.setLocalDescription(offer);
    await waitForIce(connection);
    if (pc !== connection) return;
    const avatar = $('offerAvatar').value.trim();
    const answer = await jsonPost('/offer', {
      sdp: connection.localDescription.sdp,
      type: connection.localDescription.type,
      avatar: avatar || undefined,
      refaudio: $('offerRefAudio').value.trim() || undefined,
      reftext: $('offerRefText').value.trim() || undefined
    });
    if (!answer.sdp || !answer.sessionid) throw new Error('服务端未返回会话信息');
    if (pc !== connection) return;
    sessionid = answer.sessionid;
    $('sessionIdDisplay').textContent = `会话 ID：${sessionid}`;
    $('avatarDisplay').textContent = `当前形象：${avatar || '服务端默认形象'}`;
    await connection.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
  } catch (error) {
    resetConnection();
    notice(`连接失败：${error.message}`, 'error');
  }
}

function stop() {
  resetConnection();
  notice('连接已断开。');
}

async function sendText() {
  const message = $('txtMessage').value.trim();
  if (!message) { notice('请先输入想说的话。', 'error'); $('txtMessage').focus(); return; }
  if (!sessionid || connectionState !== 'connected') return;
  try {
    $('btnSend').disabled = true;
    await jsonPost('/human', {
      sessionid,
      text: message,
      type: $('txtType').value,
      interrupt: $('txtInterrupt').checked
    });
    $('txtMessage').value = '';
    notice('内容已提交，请通过数字人音视频聆听回应。', 'success');
  } catch (error) {
    notice(`发送失败：${error.message}`, 'error');
  } finally {
    $('btnSend').disabled = connectionState !== 'connected';
  }
}

async function uploadAudio() {
  const file = $('audioFile').files[0];
  if (!file) { notice('请先选择音频文件。', 'error'); return; }
  const form = new FormData();
  form.append('sessionid', sessionid);
  form.append('file', file);
  try {
    await requestJson('/humanaudio', { method: 'POST', body: form });
    notice('音频已提交给数字人。', 'success');
  } catch (error) { notice(`音频上传失败：${error.message}`, 'error'); }
}

async function interruptTalk() {
  try {
    await jsonPost('/interrupt_talk', { sessionid });
    notice('已打断当前播报。', 'success');
  } catch (error) { notice(`打断失败：${error.message}`, 'error'); }
}

async function checkSpeaking() {
  try {
    const data = await jsonPost('/is_speaking', { sessionid });
    notice(data.data ? '数字人正在播报。' : '数字人当前没有播报。');
  } catch (error) { notice(`状态查询失败：${error.message}`, 'error'); }
}

async function toggleRecord() {
  try {
    await jsonPost('/record', { sessionid, type: recording ? 'end_record' : 'start_record' });
    recording = !recording;
    $('btnRecToggle').textContent = recording ? '停止录制' : '开始录制';
    $('btnDownload').disabled = recording;
    notice(recording ? '已开始录制。' : '录制已结束，可以下载视频。', 'success');
  } catch (error) { notice(`录制操作失败：${error.message}`, 'error'); }
}

async function setAudiotype() {
  const audiotype = Number.parseInt($('audiotypeVal').value, 10);
  if (!Number.isInteger(audiotype) || audiotype < 2) {
    notice('请输入不小于 2 的动作片段索引。', 'error');
    return;
  }
  try {
    await jsonPost('/set_audiotype', { sessionid, audiotype });
    notice('动作片段切换请求已提交。', 'success');
  } catch (error) { notice(`动作切换失败：${error.message}`, 'error'); }
}

async function loadServerConfig() {
  try {
    const data = await requestJson('/api/admin/config');
    const config = data.data.config;
    $('offerAvatar').value = config.avatar_id || '';
    $('offerRefAudio').placeholder = config.REF_FILE || '由服务端配置决定';
    $('modelHint').textContent = `当前渲染模型：${config.model} · 默认形象：${config.avatar_id || '未配置'}`;
    $('llmHint').textContent = config.llm_provider === 'local'
      ? (config.llm_base_url && config.llm_model ? '本地模型地址与名称已配置；连接后可尝试智能回答。' : '本地模型尚未配置：请填写 config.yaml 的 llm_base_url 和 llm_model。')
      : '当前使用云端模型；智能回答需要服务端配置对应 API Key。';
  } catch (error) {
    $('modelHint').textContent = '无法读取服务端配置；请先启动 LiveTalking 服务。';
    $('llmHint').textContent = '无法读取大模型配置；原文播报仍可在服务端启动后使用。';
  }
}

$('btnStart').addEventListener('click', start);
$('btnStop').addEventListener('click', stop);
$('btnSend').addEventListener('click', sendText);
$('btnUpload').addEventListener('click', uploadAudio);
$('btnInterrupt').addEventListener('click', interruptTalk);
$('btnSpeaking').addEventListener('click', checkSpeaking);
$('btnRecToggle').addEventListener('click', toggleRecord);
$('btnDownload').addEventListener('click', () => {
  if (sessionid) window.open(`/record/${encodeURIComponent(sessionid)}`, '_blank');
});
$('btnAudiotype').addEventListener('click', setAudiotype);
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  $('txtMessage').value = button.dataset.prompt;
  $('txtMessage').focus();
}));
$('txtMessage').addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) sendText();
});
loadServerConfig();
