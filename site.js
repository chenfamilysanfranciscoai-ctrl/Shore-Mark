// Shoremark: shared behavior (the mobile menu button).
(function(){
  var btn = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (!btn || !nav) return;
  function setOpen(open){
    nav.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    var label = btn.querySelector('.nav-toggle-label');
    if (label) label.textContent = open ? 'Close' : 'Menu';
  }
  btn.addEventListener('click', function(){ setOpen(!nav.classList.contains('open')); });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && nav.classList.contains('open')) { setOpen(false); btn.focus(); }
  });
  document.addEventListener('click', function(e){
    if (nav.classList.contains('open') && !nav.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  window.addEventListener('resize', function(){ if (window.innerWidth > 880) setOpen(false); });
})();
