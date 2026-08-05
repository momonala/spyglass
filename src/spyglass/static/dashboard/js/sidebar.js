/* Sidebar collapse toggle. State persists across pages via localStorage. */
(function () {
  const toggle = document.getElementById('sidebarToggle');
  const COLLAPSED = 'sidebar-collapsed';

  function apply(collapsed) {
    document.body.classList.toggle(COLLAPSED, collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  }

  apply(localStorage.getItem('sidebarCollapsed') === '1');

  toggle.addEventListener('click', () => {
    const next = !document.body.classList.contains(COLLAPSED);
    localStorage.setItem('sidebarCollapsed', next ? '1' : '0');
    apply(next);
  });
})();
