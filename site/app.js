/* Progressive enhancement only: all evidence and links are pre-rendered. */
(() => {
  'use strict';
  const families = [...document.querySelectorAll('.family')];
  const links = [...document.querySelectorAll('.family-link')];
  const status = document.getElementById('selection-status');
  if (!families.length) return;
  function select(id, announce = false) {
    const selected = families.find(family => family.id === id);
    if (!selected) return false;
    families.forEach(family => { family.hidden = family !== selected; });
    links.forEach(link => {
      if (link.hash === `#${id}`) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    if (announce) status.textContent = `Selected example: ${selected.querySelector('h2').textContent}`;
    return true;
  }
  function readHash() {
    // Unknown hashes leave the current example intact, including benchmark links.
    select(location.hash.slice(1), true);
  }
  select(location.hash.slice(1)) || select(families[0].id);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#family-"]');
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const id = link.hash.slice(1);
    if (!select(id, true)) return;
    event.preventDefault();
    if (location.hash !== link.hash) history.pushState(null, '', link.hash);
    const title = document.getElementById(id).querySelector('h2');
    title.focus({preventScroll: true});
    document.getElementById(id).scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  });
  window.addEventListener('hashchange', readHash);
  window.addEventListener('popstate', readHash);
})();
