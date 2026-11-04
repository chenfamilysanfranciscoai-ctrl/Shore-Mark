// Shoremark: talks to Supabase with plain fetch (no library). Used by spot.html,
// needs.html and admin.html.
(function(){
  var C = window.SHOREMARK_CONFIG || {};
  var CAUSES = [
    ['litter', 'Litter and trash'], ['habitat', 'Degrading habitat'], ['invasive', 'Invasive plants'],
    ['dumping', 'Illegal dumping'], ['erosion', 'Erosion'], ['water', 'Polluted water'], ['other', 'Something else']
  ];
  var LABEL = {}; CAUSES.forEach(function(c){ LABEL[c[0]] = c[1]; });

  function configured(){ return !!(C.SUPABASE_URL && C.SUPABASE_ANON_KEY); }
  function base(){ return String(C.SUPABASE_URL || '').replace(/\/+$/, ''); }
  function headers(token, extra){
    var h = { apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + (token || C.SUPABASE_ANON_KEY) };
    if (extra) Object.keys(extra).forEach(function(k){ h[k] = extra[k]; });
    return h;
  }
  async function check(res){
    if (res.ok) return res;
    var msg = '';
    try { var j = await res.json(); msg = j.message || j.msg || j.error_description || j.error || ''; } catch (e) {}
    var err = new Error(msg || ('Request failed (' + res.status + ')'));
    err.status = res.status;
    throw err;
  }
  function uuid(){
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    var h = Array.from(b, function(x){ return x.toString(16).padStart(2, '0'); }).join('');
    return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
  }
  function photoUrl(path){ return base() + '/storage/v1/object/public/report-photos/' + encodeURIComponent(path); }

  // Re-draw a photo onto a canvas: shrinks it and drops hidden data such as GPS in the EXIF.
  async function cleanPhoto(file){
    var bmp;
    try { bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }); }
    catch (e) { bmp = await createImageBitmap(file); }
    var max = 1600, s = Math.min(1, max / Math.max(bmp.width, bmp.height));
    var w = Math.max(1, Math.round(bmp.width * s)), h = Math.max(1, Math.round(bmp.height * s));
    var cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    cv.getContext('2d').drawImage(bmp, 0, 0, w, h);
    if (bmp.close) bmp.close();
    return await new Promise(function(res, rej){
      cv.toBlob(function(b){ b ? res(b) : rej(new Error('Could not read that photo.')); }, 'image/jpeg', 0.82);
    });
  }
  async function uploadPhoto(blob){
    var path = uuid() + '.jpg';
    var res = await fetch(base() + '/storage/v1/object/report-photos/' + path, {
      method: 'POST', headers: headers(null, { 'Content-Type': 'image/jpeg', 'x-upsert': 'false' }), body: blob
    });
    await check(res);
    return path;
  }
  async function submitReport(r){
    var res = await fetch(base() + '/rest/v1/reports', {
      method: 'POST', headers: headers(null, { 'Content-Type': 'application/json', Prefer: 'return=minimal' }), body: JSON.stringify(r)
    });
    await check(res);
  }
  async function listPublic(){
    var res = await fetch(base() + '/rest/v1/public_reports?select=*&order=created_at.desc&limit=300', { headers: headers() });
    await check(res);
    return await res.json();
  }
  async function submitInterest(i){
    var res = await fetch(base() + '/rest/v1/host_interest', {
      method: 'POST', headers: headers(null, { 'Content-Type': 'application/json', Prefer: 'return=minimal' }), body: JSON.stringify(i)
    });
    await check(res);
  }
  // ---- admin (needs a logged-in admin token) ----
  async function login(email, password){
    var res = await fetch(base() + '/auth/v1/token?grant_type=password', {
      method: 'POST', headers: headers(null, { 'Content-Type': 'application/json' }), body: JSON.stringify({ email: email, password: password })
    });
    await check(res);
    return (await res.json()).access_token;
  }
  async function adminList(token, table, query){
    var res = await fetch(base() + '/rest/v1/' + table + '?' + query, { headers: headers(token) });
    await check(res);
    return await res.json();
  }
  async function adminUpdate(token, id, patch){
    var res = await fetch(base() + '/rest/v1/reports?id=eq.' + encodeURIComponent(id), {
      method: 'PATCH', headers: headers(token, { 'Content-Type': 'application/json', Prefer: 'return=minimal' }), body: JSON.stringify(patch)
    });
    await check(res);
  }
  async function adminDeleteReport(token, id){
    var res = await fetch(base() + '/rest/v1/reports?id=eq.' + encodeURIComponent(id), { method: 'DELETE', headers: headers(token) });
    await check(res);
  }
  async function adminDeletePhoto(token, path){
    var res = await fetch(base() + '/storage/v1/object/report-photos/' + encodeURIComponent(path), { method: 'DELETE', headers: headers(token) });
    await check(res);
  }
  window.SM = {
    CAUSES: CAUSES, label: function(k){ return LABEL[k] || k; }, configured: configured, photoUrl: photoUrl,
    cleanPhoto: cleanPhoto, uploadPhoto: uploadPhoto, submitReport: submitReport, listPublic: listPublic, submitInterest: submitInterest,
    login: login, adminList: adminList, adminUpdate: adminUpdate, adminDeleteReport: adminDeleteReport, adminDeletePhoto: adminDeletePhoto
  };
})();
