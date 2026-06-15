import { ref, watch, type Ref } from "vue";

type Theme = "dark" | "light";

const STORAGE_KEY = "hd-theme";

function readStored(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "dark" || stored === "light") return stored;
  // Respect OS preference; default to dark
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function apply(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  // Element Plus dark mode class
  root.classList.toggle("dark", theme === "dark");

  // Set a meta theme-color for browser chrome
  const meta = (
    document.querySelector('meta[name="theme-color"]') ??
    (() => {
      const m = document.createElement("meta");
      m.name = "theme-color";
      document.head.appendChild(m);
      return m;
    })()
  ) as HTMLMetaElement;
  meta.content = theme === "dark" ? "#050914" : "#f5f7fa";
}

const current = ref<Theme>(readStored());

// Apply on first load
apply(current.value);

/** Toggle between light and dark. Returns the new theme. */
function toggle(): Theme {
  current.value = current.value === "dark" ? "light" : "dark";
  return current.value;
}

/** Set a specific theme. */
function set(theme: Theme) {
  current.value = theme;
}

// Persist changes
watch(current, (val) => {
  localStorage.setItem(STORAGE_KEY, val);
  apply(val);
});

export function useTheme(): {
  current: Ref<Theme>;
  toggle: () => Theme;
  set: (t: Theme) => void;
} {
  return { current, toggle, set };
}
