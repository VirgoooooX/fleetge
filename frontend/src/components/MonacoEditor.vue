<template>
  <div ref="containerRef" class="monaco-editor-container" :class="{ disabled: disabled }" />
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import YamlWorker from "monaco-yaml/yaml.worker?worker";

// ─── Self-contained MonacoEnvironment setup ───────────────────────────────────
// This must happen before any monaco.editor calls.
// Using Vite's native ?worker import so workers are bundled as separate chunks.
if (!(window as any).__monacoWorkerSetup) {
  (window as any).MonacoEnvironment = {
    getWorker(_: unknown, label: string) {
      if (label === "yaml") {
        return new YamlWorker();
      }
      return new EditorWorker();
    },
  };
  (window as any).__monacoWorkerSetup = true;
}

// ─── Props & Emits ──────────────────────────────────────────────────────────

const props = withDefaults(
  defineProps<{
    modelValue: string;
    language?: string;
    readonly?: boolean;
    disabled?: boolean;
    height?: string;
    lineNumbers?: "on" | "off";
    wordWrap?: "on" | "off";
  }>(),
  {
    language: "yaml",
    readonly: false,
    disabled: false,
    height: "480px",
    lineNumbers: "on",
    wordWrap: "off",
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

// ─── Refs ────────────────────────────────────────────────────────────────────

const containerRef = ref<HTMLElement | null>(null);
let editor: monaco.editor.IStandaloneCodeEditor | null = null;
let resizeObserver: ResizeObserver | null = null;
let themeObserver: MutationObserver | null = null;

// ─── Theme helpers ────────────────────────────────────────────────────────────

function getMonacoTheme(): string {
  return document.documentElement.dataset.theme === "light" ? "fleetge-light" : "fleetge-dark";
}

let themesRegistered = false;
function ensureThemes() {
  if (themesRegistered) return;
  themesRegistered = true;

  monaco.editor.defineTheme("fleetge-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#0d1117",
      "editor.foreground": "#e6edf3",
      "editorLineNumber.foreground": "#3d444d",
      "editorLineNumber.activeForeground": "#848d97",
      "editor.lineHighlightBackground": "#161b22",
      "editor.selectionBackground": "#264f78",
      "editorCursor.foreground": "#e6edf3",
      "editor.inactiveSelectionBackground": "#1f2937",
      "editorGutter.background": "#0d1117",
      "scrollbarSlider.background": "#21262d80",
      "scrollbarSlider.hoverBackground": "#30363d",
      "scrollbarSlider.activeBackground": "#484f58",
    },
  });
  monaco.editor.defineTheme("fleetge-light", {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#f8fafc",
      "editor.foreground": "#0f172a",
      "editorLineNumber.foreground": "#94a3b8",
      "editorLineNumber.activeForeground": "#475569",
      "editor.lineHighlightBackground": "#f1f5f9",
      "editor.selectionBackground": "#bfdbfe",
      "editorCursor.foreground": "#0f172a",
      "editor.inactiveSelectionBackground": "#e2e8f0",
      "editorGutter.background": "#f8fafc",
      "scrollbarSlider.background": "#cbd5e180",
      "scrollbarSlider.hoverBackground": "#94a3b8",
      "scrollbarSlider.activeBackground": "#64748b",
    },
  });
}

// ─── Editor lifecycle ─────────────────────────────────────────────────────────

onMounted(() => {
  if (!containerRef.value) return;

  ensureThemes();

  editor = monaco.editor.create(containerRef.value, {
    value: props.modelValue,
    language: props.language,
    theme: getMonacoTheme(),
    readOnly: props.readonly || props.disabled,
    minimap: { enabled: false },
    fontSize: 13,
    lineHeight: 20,
    fontFamily:
      "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace",
    fontLigatures: true,
    lineNumbers: props.lineNumbers,
    lineDecorationsWidth: props.lineNumbers === "off" ? 0 : 10,
    lineNumbersMinChars: props.lineNumbers === "off" ? 0 : 5,
    glyphMargin: false,
    folding: true,
    scrollBeyondLastLine: false,
    wordWrap: props.wordWrap,
    automaticLayout: false,
    renderWhitespace: "boundary",
    tabSize: 2,
    insertSpaces: true,
    scrollbar: {
      verticalScrollbarSize: 6,
      horizontalScrollbarSize: 6,
      useShadows: false,
    },
    overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true,
    renderLineHighlight: "gutter",
    smoothScrolling: true,
    cursorBlinking: "smooth",
    cursorSmoothCaretAnimation: "on",
    padding: { top: 12, bottom: 12 },
    contextmenu: true,
    quickSuggestions: false,
  });

  // Emit changes back to parent
  editor.onDidChangeModelContent(() => {
    const value = editor!.getValue();
    if (value !== props.modelValue) {
      emit("update:modelValue", value);
    }
  });

  // ResizeObserver for layout updates
  resizeObserver = new ResizeObserver(() => {
    editor?.layout();
  });
  resizeObserver.observe(containerRef.value);

  // MutationObserver for theme switching
  themeObserver = new MutationObserver(() => {
    monaco.editor.setTheme(getMonacoTheme());
  });
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  themeObserver?.disconnect();
  editor?.dispose();
  editor = null;
});

// ─── Watchers ─────────────────────────────────────────────────────────────────

// Sync external value changes into the editor (e.g. loading from server)
watch(
  () => props.modelValue,
  (newVal) => {
    if (editor && editor.getValue() !== newVal) {
      const model = editor.getModel();
      if (model) {
        model.pushEditOperations(
          [],
          [
            {
              range: model.getFullModelRange(),
              text: newVal,
            },
          ],
          () => null
        );
      }
    }
  }
);

// Sync readOnly / disabled state
watch(
  () => [props.readonly, props.disabled],
  ([ro, dis]) => {
    editor?.updateOptions({ readOnly: (ro as boolean) || (dis as boolean) });
  }
);

// Sync language (when tabs switch)
watch(
  () => props.language,
  (lang) => {
    const model = editor?.getModel();
    if (model) {
      monaco.editor.setModelLanguage(model, lang);
    }
  }
);

// Sync lineNumbers option
watch(
  () => props.lineNumbers,
  (ln) => {
    editor?.updateOptions({
      lineNumbers: ln,
      lineDecorationsWidth: ln === "off" ? 0 : 10,
      lineNumbersMinChars: ln === "off" ? 0 : 5,
    });
  }
);

// Sync wordWrap option
watch(
  () => props.wordWrap,
  (wrap) => {
    editor?.updateOptions({ wordWrap: wrap });
  }
);
</script>

<style scoped>
.monaco-editor-container {
  width: 100%;
  height: v-bind(height);
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-color, #30363d);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  position: relative;
}

.monaco-editor-container:focus-within {
  border-color: var(--el-color-primary, #409eff);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.15);
}

.monaco-editor-container.disabled {
  opacity: 0.55;
  pointer-events: none;
}

.monaco-editor-container :deep(.monaco-editor) {
  border-radius: 8px;
}

.monaco-editor-container :deep(.monaco-scrollable-element > .scrollbar.vertical .slider) {
  border-radius: 3px;
}

.monaco-editor-container :deep(.monaco-scrollable-element > .scrollbar.horizontal .slider) {
  border-radius: 3px;
}
</style>
