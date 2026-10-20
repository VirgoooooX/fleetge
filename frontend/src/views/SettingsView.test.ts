import component from "./SettingsView.vue?raw";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

// Exercise the actual SFC handlers without requiring a browser or a DOM renderer.
const script = component.split('<script setup lang="ts">')[1]!.split("</script>")[0]!;
const parsed = ts.createSourceFile("SettingsView.ts", script, ts.ScriptTarget.Latest, true);
const handlers = new Set([
  "openCreateHostDialog", "openEditHostDialog", "closeHostDialog",
  "prepareHostPayload", "resetSubscriptionForm", "applySubscription", "saveHostForm",
]);
const selected = parsed.statements.filter((node) =>
  (ts.isFunctionDeclaration(node) && node.name && handlers.has(node.name.text)) ||
  (ts.isVariableStatement(node) && node.declarationList.declarations.some((decl) =>
    ts.isIdentifier(decl.name) && decl.name.text === "hostDialogRequest")),
).map((node) => node.getText(parsed)).join("\n");
const code = ts.transpile(selected, { target: ts.ScriptTarget.ES2022 });

function fixture() {
  const value = (initial: unknown = null) => ({ value: initial });
  const ctx = {
    hostForm: { agent_token: "previous-input" } as Record<string, any>,
    subscriptionForm: {} as Record<string, any>,
    hostFormMode: value("edit"), hostSubscriptionLoaded: value(false),
    hostDialogPanels: value([]), hostDialogVisible: value(false),
    hostFormLoading: value(false), renewalDialogVisible: value(false),
    hostFormRef: value({ clearValidate: vi.fn(), validate: vi.fn().mockResolvedValue(true) }),
    store: { hosts: [], createHost: vi.fn().mockResolvedValue({}), updateHost: vi.fn().mockResolvedValue({}) },
    apiClient: { get: vi.fn(), put: vi.fn().mockResolvedValue({}) },
    ElMessage: { error: vi.fn(), success: vi.fn() }, t: (key: string) => key,
  };
  const handlers = new Function("ctx", `with (ctx) { ${code}; return {
    openCreateHostDialog, openEditHostDialog, closeHostDialog, prepareHostPayload, saveHostForm
  }; }`)(ctx);
  return { ctx, handlers };
}

function deferred() {
  let resolve!: (data: any) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const host = (id: string) => ({ host_id: id, agent_url: `http://${id}`, display_name: id });

describe("Host editing isolation", () => {
  it("clears the previous Host token before preparing another Host update", async () => {
    const { ctx, handlers } = fixture();
    ctx.apiClient.get.mockResolvedValue({ data: { provider: "B" } });
    await handlers.openEditHostDialog(host("b"));
    expect(ctx.hostForm.agent_token).toBe("");
    expect(handlers.prepareHostPayload().agent_token).toBeNull();
  });

  it("ignores a previous Host response after switching dialogs", async () => {
    const { ctx, handlers } = fixture();
    const a = deferred(), b = deferred();
    ctx.apiClient.get.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = handlers.openEditHostDialog(host("a"));
    handlers.closeHostDialog();
    const second = handlers.openEditHostDialog(host("b"));
    b.resolve({ data: { provider: "provider-b" } });
    await second;
    a.resolve({ data: { provider: "provider-a" } });
    await first;
    expect(ctx.hostForm.host_id).toBe("b");
    expect(ctx.subscriptionForm.provider).toBe("provider-b");
  });

  it("does not unlock a new form when an older request fails", async () => {
    const { ctx, handlers } = fixture();
    const a = deferred(), b = deferred();
    ctx.apiClient.get.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    const first = handlers.openEditHostDialog(host("a"));
    const second = handlers.openEditHostDialog(host("b"));
    a.reject(new Error("old request failed"));
    await first;
    expect(ctx.hostFormLoading.value).toBe(true);
    expect(ctx.hostSubscriptionLoaded.value).toBe(false);
    expect(ctx.ElMessage.error).not.toHaveBeenCalled();
    b.resolve({ data: { provider: "B" } });
    await second;
    expect(ctx.hostFormLoading.value).toBe(false);
  });

  it("saves the original Host snapshot if the user switches during a save", async () => {
    const { ctx, handlers } = fixture();
    ctx.apiClient.get.mockResolvedValueOnce({ data: { provider: "provider-a" } })
      .mockResolvedValueOnce({ data: { provider: "provider-b" } });
    await handlers.openEditHostDialog(host("a"));
    const update = deferred();
    ctx.store.updateHost.mockReturnValueOnce(update.promise);
    const saving = handlers.saveHostForm();
    await vi.waitFor(() => expect(ctx.store.updateHost).toHaveBeenCalled());
    handlers.closeHostDialog();
    await handlers.openEditHostDialog(host("b"));
    update.resolve({});
    await saving;
    expect(ctx.apiClient.put).toHaveBeenCalledWith("/api/hosts/a/subscription", expect.objectContaining({ provider: "provider-a" }));
    expect(ctx.hostForm.host_id).toBe("b");
    expect(ctx.subscriptionForm.provider).toBe("provider-b");
    expect(ctx.hostDialogVisible.value).toBe(true);
  });

  it("invalidates pending edits when opening a create form", async () => {
    const { ctx, handlers } = fixture();
    const a = deferred();
    ctx.apiClient.get.mockReturnValueOnce(a.promise);
    const first = handlers.openEditHostDialog(host("a"));
    handlers.openCreateHostDialog();
    a.resolve({ data: { provider: "old-provider" } });
    await first;
    expect(ctx.hostFormMode.value).toBe("create");
    expect(ctx.subscriptionForm.provider).toBe("");
    expect(ctx.hostForm.agent_token).toBe("");
  });
});
