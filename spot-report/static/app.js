/* Spot India: capture -> on-device classification -> route -> deliver.
 *
 * Classification runs entirely in the browser with transformers.js and CLIP
 * zero-shot. Why CLIP rather than an object detector: a COCO detector can say
 * "dog" but never "injured dog", and has no pothole or garbage class at all.
 * CLIP scores the photo against full sentences, so condition and scene are
 * reachable without training anything.
 */

const TRANSFORMERS_URL = 'https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2';

const $ = (id) => document.getElementById(id);
const steps = [...document.querySelectorAll('.step')];

const state = {
  cfg: null,
  photo: null,          // data URL
  photoBlob: null,
  facing: 'environment',
  stream: null,
  category: null,
  confidence: null,
  alternatives: [],
  answer: null,
  location: { lat: null, lng: null, accuracy: null },
  located: null,
  report: null,
  links: null,
};

/* ---------- step machine ---------- */
function show(name) {
  steps.forEach((s) => { s.hidden = s.dataset.step !== name; });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ---------- boot ---------- */
async function boot() {
  try {
    state.cfg = await (await fetch('/api/config')).json();
  } catch {
    $('camera-err').textContent = 'Could not reach the server. Check your connection.';
    $('camera-err').hidden = false;
    return;
  }
  buildPicker();
  const c = state.cfg.capabilities;
  $('cap-badge').textContent = c.server_email
    ? 'Email delivery active'
    : 'Email delivery not configured: you will send from your own app';
  $('cap-badge').className = c.server_email ? 'badge ok' : 'badge warn';
}

/* ---------- camera ---------- */
async function openCamera() {
  $('camera-err').hidden = true;
  if (!navigator.mediaDevices?.getUserMedia) {
    return fail('This browser cannot open the camera. Use "Upload instead".');
  }
  try {
    stopCamera();
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: state.facing, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    const v = $('video');
    v.srcObject = state.stream;
    await v.play();
    // One action per state: while the camera is live, Capture is the only
    // choice on offer. Flip moves onto the frame, upload steps aside.
    $('camera-idle').hidden = true;
    $('btn-open').hidden = true;
    $('btn-shoot').hidden = false;
    $('btn-flip').hidden = false;
    $('alt-action').hidden = true;
    $('shot').hidden = true;
    v.hidden = false;
    primeLocation();
  } catch (e) {
    const msg = e.name === 'NotAllowedError'
      ? 'Camera permission was denied. Allow it in your browser settings, or use "Upload instead".'
      : e.name === 'NotFoundError'
        ? 'No camera found on this device. Use "Upload instead".'
        : `Could not start the camera (${e.name}). Use "Upload instead".`;
    fail(msg);
  }
}

function fail(msg) {
  $('camera-err').textContent = msg;
  $('camera-err').hidden = false;
  // The message points the reporter at upload, so it must be on screen.
  $('alt-action').hidden = false;
}

function stopCamera() {
  state.stream?.getTracks().forEach((t) => t.stop());
  state.stream = null;
}

function capture() {
  const v = $('video');
  const c = $('canvas');
  // Downscale to 1024px on the long edge: plenty for CLIP and for a responder
  // to see, and small enough to attach to an email over a weak connection.
  const max = 1024;
  const scale = Math.min(1, max / Math.max(v.videoWidth, v.videoHeight));
  c.width = Math.round(v.videoWidth * scale);
  c.height = Math.round(v.videoHeight * scale);
  c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
  c.toBlob((blob) => {
    state.photoBlob = blob;
    state.photo = c.toDataURL('image/jpeg', 0.82);
    stopCamera();
    $('video').hidden = true;
    $('shot').src = state.photo;
    $('shot').hidden = false;
    analyse();
  }, 'image/jpeg', 0.82);
}

function fromFile(file) {
  const fr = new FileReader();
  fr.onload = () => {
    const img = new Image();
    img.onload = () => {
      const c = $('canvas');
      const max = 1024;
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      state.photo = c.toDataURL('image/jpeg', 0.82);
      c.toBlob((b) => { state.photoBlob = b; }, 'image/jpeg', 0.82);
      stopCamera();
      primeLocation();
      analyse();
    };
    img.src = fr.result;
  };
  fr.readAsDataURL(file);
}

/* ---------- classification ---------- */
let classifier = null;

async function getClassifier(onProgress) {
  if (classifier) return classifier;
  const { pipeline, env } = await import(TRANSFORMERS_URL);
  env.allowLocalModels = false;       // always fetch from the HF hub
  env.useBrowserCache = true;         // cache weights so this is a one-time cost
  classifier = await pipeline('zero-shot-image-classification', state.cfg.model.id, {
    quantized: true,
    progress_callback: (p) => {
      if (p.status === 'progress' && p.total) {
        onProgress(Math.round((p.loaded / p.total) * 100), p.file);
      }
    },
  });
  return classifier;
}

async function analyse() {
  show('analyse');
  $('analyse-thumb').src = state.photo;
  $('analyse-wrap').classList.add('locking');
  $('analyse-err').hidden = true;
  setProgress(4);
  $('analyse-status').textContent = 'Loading the vision model…';

  try {
    const clf = await getClassifier((pct, file) => {
      setProgress(Math.max(5, Math.min(90, pct)));
      $('analyse-status').textContent = `Downloading model… ${pct}%`;
      $('analyse-note').textContent = file ? `Fetching ${file}` : '';
    });

    $('analyse-status').textContent = 'Reading the photo…';
    setProgress(94);

    const prompts = state.cfg.prompts;
    const out = await clf(state.photo, prompts.map((p) => p.text));

    // out is [{label, score}] over our prompts. Fold prompt scores up into
    // their categories, keeping each category's best-scoring phrasing.
    const byText = new Map(prompts.map((p) => [p.text, p.category]));
    const best = new Map();
    for (const row of out) {
      const cat = byText.get(row.label);
      if (!cat) continue;
      if (!best.has(cat) || row.score > best.get(cat)) best.set(cat, row.score);
    }
    const ranked = [...best.entries()]
      .map(([id, score]) => ({ id, score }))
      .sort((a, b) => b.score - a.score);

    setProgress(100);
    $('analyse-wrap').classList.remove('locking');
    decide(ranked);
  } catch (e) {
    $('analyse-err').textContent =
      `On-device analysis failed (${e.message || e.name}). Pick the category yourself.`;
    $('analyse-err').hidden = false;
    setTimeout(() => show('pick'), 1200);
  }
}

function setProgress(pct) { $('progress-bar').style.width = `${pct}%`; }

function catById(id) { return state.cfg.categories.find((c) => c.id === id); }

function decide(ranked) {
  const top = ranked[0];
  const min = state.cfg.model.min_confidence;

  // A control prompt winning, or everything scoring low, means we should not
  // guess. Showing the picker beats routing a wrong report to a real authority.
  if (!top || top.id === '__none__' || top.score < min) {
    show('pick');
    $('capture-hint').textContent = '';
    return;
  }

  state.category = top.id;
  state.confidence = top.score;
  state.alternatives = ranked
    .filter((r) => r.id !== top.id && r.id !== '__none__')
    .slice(0, 4)
    .map((r) => ({ id: r.id, name: catById(r.id)?.name || r.id, score: r.score }));

  renderConfirm();
  show('confirm');
}

function renderConfirm() {
  const c = catById(state.category);
  const sev = state.cfg.severity[c.severity];
  $('confirm-thumb').src = state.photo;
  $('verdict-name').textContent = c.name;
  $('verdict-sev').textContent = sev.label;
  $('verdict-sev').className = `sev sev-${c.severity}`;
  // Category, confidence and severity read as chips on the photo itself.
  $('chip-category').textContent = c.name;
  $('chip-conf').textContent = state.confidence == null
    ? 'Manual'
    : `${Math.round(state.confidence * 100)}%`;
  $('verdict-conf').textContent = state.confidence == null
    ? `Chosen by you. ${sev.blurb}`
    : sev.blurb;
  // Categories that name people carry a caution the reporter sees up front.
  $('caution').innerHTML = c.caution || '';
  $('caution').hidden = !c.caution;
  const cta = $('call-cta');
  if (c.helpline) {
    cta.href = `tel:${c.helpline}`;
    cta.innerHTML = `<span>Call</span><span class="num">${c.helpline}</span><span>now</span>`;
    cta.className = `call-cta${c.severity === 'critical' ? ' critical' : ''}`;
    cta.hidden = false;
  } else {
    cta.hidden = true;
  }
  $('verdict-auth').innerHTML =
    `Goes to <strong>${c.authority}</strong>`
    + (c.authority_dept ? `<br><small>${c.authority_dept}</small>` : '')
    + ((c.extra_helplines && c.extra_helplines.length)
        ? `<br><small class="muted">Also: ${c.extra_helplines
             .map((h) => `${h.label} <a class="helpline" href="tel:${h.number}">${h.number}</a>`)
             .join(' · ')}</small>`
        : '');

  // One targeted follow-up question. Responders consistently need this detail
  // and a photo cannot answer it.
  state.answer = null;
  if (c.ask) {
    $('followup-q').textContent = c.ask;
    const chips = $('followup-chips');
    chips.innerHTML = '';
    ['Yes', 'No', 'Not sure'].forEach((label) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip';
      b.textContent = label;
      b.onclick = () => {
        state.answer = label;
        [...chips.children].forEach((x) => x.classList.remove('on'));
        b.classList.add('on');
      };
      chips.appendChild(b);
    });
    $('followup').hidden = false;
  } else {
    $('followup').hidden = true;
  }

  if (state.alternatives.length) {
    $('alts-list').innerHTML = state.alternatives
      .map((a) => `<li><button type="button" data-id="${a.id}">${a.name}</button>
                   <span>${Math.round(a.score * 100)}%</span></li>`).join('');
    $('alts-list').querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        state.category = b.dataset.id;
        state.confidence = state.alternatives.find((a) => a.id === b.dataset.id)?.score ?? null;
        renderConfirm();
      };
    });
    $('alts').hidden = false;
  } else {
    $('alts').hidden = true;
  }
}

function buildPicker() {
  const host = $('pick-groups');
  host.innerHTML = '';
  for (const group of state.cfg.groups) {
    const wrap = document.createElement('section');
    wrap.className = 'pick-group';
    wrap.innerHTML = `<h2>${group}</h2>`;
    const grid = document.createElement('div');
    grid.className = 'pick-grid';
    state.cfg.categories.filter((c) => c.group === group).forEach((c) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pick';
      b.innerHTML = `<span class="pick-name">${c.name}</span>
                     <span class="sev sev-${c.severity}">${state.cfg.severity[c.severity].label}</span>
                     <span class="pick-auth">Goes to ${c.authority}</span>`;
      b.onclick = () => {
        state.category = c.id;
        state.confidence = null;
        state.alternatives = [];
        renderConfirm();
        show('confirm');
      };
      grid.appendChild(b);
    });
    wrap.appendChild(grid);
    host.appendChild(wrap);
  }
}

/* ---------- location ---------- */
function primeLocation() {
  if (!navigator.geolocation) {
    $('loc-main').textContent = 'This browser cannot provide location';
    return;
  }
  $('loc-main').textContent = 'Finding your location…';
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      state.location = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
      };
      try {
        const r = await fetch('/api/locate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(state.location),
        });
        state.located = await r.json();
        state.located.accuracy = state.location.accuracy;
        $('loc-main').textContent = state.located.short || 'Location found';
        $('loc-sub').textContent =
          `${state.location.lat.toFixed(5)}, ${state.location.lng.toFixed(5)}`
          + (state.location.accuracy ? ` · ±${Math.round(state.location.accuracy)} m` : '');
      } catch {
        $('loc-main').textContent = 'Coordinates captured';
        $('loc-sub').textContent = `${state.location.lat.toFixed(5)}, ${state.location.lng.toFixed(5)}`;
      }
    },
    (err) => {
      const msg = err.code === 1
        ? 'Location permission denied. The report can still be sent without it.'
        : 'Could not get a location fix. The report can still be sent without it.';
      $('loc-main').textContent = msg;
      $('loc-sub').textContent = '';
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  );
}

/* ---------- review + send ---------- */
async function review() {
  const payload = {
    category: state.category,
    confidence: state.confidence,
    alternatives: state.alternatives,
    answer: state.answer,
    note: $('note').value.trim() || null,
    reporter: $('reporter').value.trim() || null,
    location: state.located || state.location,
  };
  const r = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  state.report = d.report;
  state.links = d.links;

  const a = d.report.authority;
  const sev = d.report.severity;
  const nb = d.report.nearby;
  $('route-strip').innerHTML =
    `<span class="sev sev-${sev.id}">${sev.label}</span>
     <span class="route-to"><strong>${a.public_name}</strong><br><small>${a.dept}</small></span>
     ${a.helpline ? `<a class="helpline" href="tel:${a.helpline}">Call ${a.helpline}</a>` : ''}`;
  $('route-strip').classList.add('card');
  $('nearby-card').innerHTML = nb
    ? `<p class="nearby-head">Nearest help to the scene</p>
       <p class="nearby-main">${nb.name}<span class="nearby-dist">${nb.distance_km} km away</span></p>
       <p class="nearby-sub">
         ${nb.phone ? `<a href="tel:${nb.phone}">${nb.phone}</a> · ` : ''}
         <a href="${nb.maps}" target="_blank" rel="noopener">Open in Maps</a></p>`
    : '';
  $('nearby-card').hidden = !nb;
  // During testing delivery is mocked; say so plainly rather than implying a
  // real department received it.
  $('test-note').innerHTML = a.mock
    ? `Testing mode: the report is delivered to the product owner
       (${a.email}, +${a.phone_e164}), not yet to ${a.public_name}.`
    : '';
  $('test-note').hidden = !a.mock;
  $('message-preview').textContent = `Subject: ${d.report.subject}\n\n${d.report.body}`;
  show('review');
}

async function send() {
  const btn = $('btn-send');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  $('send-err').hidden = true;
  try {
    const r = await fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        category: state.category,
        confidence: state.confidence,
        alternatives: state.alternatives,
        answer: state.answer,
        note: $('note').value.trim() || null,
        reporter: $('reporter').value.trim() || null,
        reply_to: $('reply_to').value.trim() || null,
        location: state.located || state.location,
        photo: state.photo,
      }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'submit failed');
    done(d);
  } catch (e) {
    $('send-err').textContent = `Could not submit: ${e.message}. Your report is not lost: go back and use the WhatsApp or email button.`;
    $('send-err').hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send to authority';
  }
}

function done(d) {
  const a = d.report.authority;
  $('done-tid').textContent = d.tracking_id;
  $('done-routed').innerHTML =
    `Filed for <strong>${a.public_name}</strong><br><small>${a.dept}</small>`
    + (a.mock ? `<br><small class="muted">Testing mode: delivered to the product owner, +${a.phone_e164}</small>` : '');

  const email = d.delivery.email;
  const bits = [];
  if (email.sent) {
    bits.push(`<p class="ok">Email delivered to ${email.to}${email.photo_attached ? ' with the photo attached' : ''}.</p>`);
  } else if (!email.configured) {
    bits.push(`<p class="warn">Server email is not configured yet, so nothing was emailed automatically. Use the buttons below to send it from your own apps.</p>`);
  } else {
    bits.push(`<p class="warn">Automatic email failed: ${email.reason}. Use the buttons below instead.</p>`);
  }
  bits.push(d.stored.saved
    ? `<p class="ok">Saved to the report database. Track it with the code above.</p>`
    : `<p class="warn">Not stored${d.stored.configured ? `: ${d.stored.reason}` : ' (database not configured yet)'}.</p>`);
  $('delivery-status').innerHTML = bits.join('');

  const L = d.delivery.links;
  const nb = d.report.nearby;
  $('done-actions').innerHTML = `
    ${a.helpline ? `<a class="primary as-button" href="tel:${a.helpline}">Call ${a.helpline} (${a.public_name})</a>` : ''}
    ${nb && nb.phone ? `<a class="ghost as-button" href="tel:${nb.phone}">Call ${nb.name}</a>` : ''}
    <a class="${a.helpline ? 'ghost' : 'primary'} as-button" href="${L.whatsapp}" target="_blank" rel="noopener">Send on WhatsApp</a>
    <a class="ghost as-button" href="${L.mailto}">Send by email</a>
    <a class="ghost as-button" href="${L.tel}">Call the authority</a>
    <a class="ghost as-button" href="/track/${d.tracking_id}">Track this report</a>`;
  // Severity drives the emergency button colour, same rule as the confirm step.

  try {
    const mine = JSON.parse(localStorage.getItem('spot_reports') || '[]');
    mine.unshift({ tid: d.tracking_id, cat: d.report.category.name, at: Date.now() });
    localStorage.setItem('spot_reports', JSON.stringify(mine.slice(0, 50)));
  } catch { /* private mode: history is a convenience, not required */ }

  show('done');
}

function reset() {
  state.photo = null; state.photoBlob = null; state.category = null;
  state.confidence = null; state.alternatives = []; state.answer = null;
  $('note').value = ''; $('shot').hidden = true; $('video').hidden = false;
  $('camera-idle').hidden = false; $('btn-open').hidden = false;
  $('btn-shoot').hidden = true; $('btn-flip').hidden = true;
  $('alt-action').hidden = false; $('camera-err').hidden = true;
  show('capture');
}

/* ---------- wiring ---------- */
$('btn-open').onclick = openCamera;
$('btn-shoot').onclick = capture;
$('btn-flip').onclick = () => {
  state.facing = state.facing === 'environment' ? 'user' : 'environment';
  openCamera();
};
$('file-input').onchange = (e) => { if (e.target.files[0]) fromFile(e.target.files[0]); };
$('btn-skip-ai').onclick = () => show('pick');
$('btn-yes').onclick = () => { primeLocation(); show('details'); };
$('btn-no').onclick = () => show('pick');
$('btn-pick-back').onclick = () => show(state.photo ? 'confirm' : 'capture');
$('btn-details-back').onclick = () => show('confirm');
$('btn-review').onclick = review;
$('btn-review-back').onclick = () => show('details');
$('btn-send').onclick = send;
$('btn-reloc').onclick = primeLocation;
$('btn-again').onclick = reset;

boot();
