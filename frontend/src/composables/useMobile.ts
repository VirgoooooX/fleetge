import { ref, onMounted, onUnmounted } from "vue";

/**
 * Reactive media-query composable for mobile detection.
 * @param breakpoint — max-width in px (default 899 — below 900px is "mobile")
 */
export function useMobile(breakpoint = 899) {
  const isMobile = ref(false);

  let mql: MediaQueryList | null = null;

  function onMatch(e: MediaQueryListEvent | MediaQueryList) {
    isMobile.value = e.matches;
  }

  onMounted(() => {
    mql = window.matchMedia(`(max-width: ${breakpoint}px)`);
    onMatch(mql);
    mql.addEventListener("change", onMatch);
  });

  onUnmounted(() => {
    if (mql) mql.removeEventListener("change", onMatch);
  });

  return { isMobile };
}
