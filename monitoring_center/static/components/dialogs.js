const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function installDialogAccessibility() {
  document.querySelectorAll("dialog").forEach((dialog) => {
    let previousFocus;
    dialog.addEventListener("show", () => { previousFocus = document.activeElement; });
    dialog.addEventListener("close", () => previousFocus?.focus?.());
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const items = [...dialog.querySelectorAll(FOCUSABLE)];
      if (!items.length) return;
      const first = items[0]; const last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
  });
}
