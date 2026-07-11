export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
export function debounce(fn, delay = 200) {
  let timeout;
  return (...args) => { clearTimeout(timeout); timeout = setTimeout(() => fn(...args), delay); };
}
