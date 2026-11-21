import { ElMessageBox } from "element-plus";
import type { MessageBoxData, ElMessageBoxOptions } from "element-plus";

export type ConfirmTone = "info" | "warning" | "danger" | "success" | "error";

export interface ConfirmOptions extends Partial<Omit<ElMessageBoxOptions, "type" | "customClass">> {
  /** 风险等级：决定弹窗色调与图标（推荐） */
  tone?: ConfirmTone;
  /** 是否隐藏关闭 × 按钮（高风险弹窗默认隐藏） */
  showClose?: boolean;
  /** 点击遮罩是否关闭（高风险弹窗默认不关闭） */
  closeOnClickModal?: boolean;
  /** 自定义 class，会自动追加 `pg-confirm tone-{tone}` */
  customClass?: string;
}

const ELEMENT_TYPE_MAP: Record<ConfirmTone, ElMessageBoxOptions["type"]> = {
  info: "info",
  warning: "warning",
  danger: "warning", // Element Plus 没有 danger，用 warning + 自定义色调
  success: "success",
  error: "error",
};

function buildOptions(opts: ConfirmOptions, tone: ConfirmTone): ElMessageBoxOptions {
  const {
    tone: _ignored,
    showClose,
    closeOnClickModal,
    customClass,
    ...rest
  } = opts;

  return {
    ...rest,
    type: ELEMENT_TYPE_MAP[tone],
    showClose: showClose ?? tone !== "danger",
    closeOnClickModal: closeOnClickModal ?? tone === "info",
    closeOnPressEscape: true,
    customClass: ["pg-confirm", `tone-${tone}`, customClass].filter(Boolean).join(" "),
    customStyle: { borderRadius: "var(--radius-lg, 8px)", ...(rest.customStyle || {}) },
  };
}

async function confirm(
  message: string | (() => string),
  title: string,
  options: ConfirmOptions = {}
): Promise<MessageBoxData> {
  const tone = options.tone || "info";
  return ElMessageBox.confirm(
    typeof message === "function" ? message() : message,
    title,
    buildOptions(options, tone)
  );
}

async function alert(
  message: string,
  title: string,
  options: ConfirmOptions = {}
): Promise<MessageBoxData> {
  const tone = options.tone || "info";
  return ElMessageBox.alert(message, title, buildOptions(options, tone));
}

export function useConfirm() {
  return { confirm, alert };
}

/** Stack 操作的风险等级映射 */
export const STACK_TONE_MAP: Record<string, ConfirmTone> = {
  start: "info",
  stop: "warning",
  down: "danger",
  restart: "warning",
  update: "info",
  delete: "danger",
  prune: "danger",
};
