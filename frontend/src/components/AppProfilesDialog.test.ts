import component from "./AppProfilesDialog.vue?raw";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

// Run the SFC's real edit handlers with the same lightweight approach as SettingsView.test.ts.
const script = component.split('<script setup lang="ts">')[1]!.split("</script>")[0]!;
const parsed = ts.createSourceFile("AppProfilesDialog.ts", script, ts.ScriptTarget.Latest, true);
const names = new Set(["resetForm", "editProfile", "removeProfile", "addProfile", "saveProfiles"]);
const selected = parsed.statements.filter((node) =>
  ts.isFunctionDeclaration(node) && node.name && names.has(node.name.text),
).map((node) => node.getText(parsed)).join("\n");
const code = ts.transpile(selected, { target: ts.ScriptTarget.ES2022 });
const entry = (pattern: string, icon: string | null = null) => ({
  stack_pattern: pattern, title: null, app_url: null, group: null, icon_value: icon,
});

function fixture(initial = [entry("old")]) {
  const emptyForm = () => ({ stack_pattern: "", title: "", app_url: "", group: "", sourceType: "none", icon_url: "", icon_file: "" });
  const ctx = {
    profiles: { value: initial }, editingIndex: { value: null as number | null },
    form: emptyForm(), emptyForm,
    formRef: { value: { validate: vi.fn().mockResolvedValue(true), clearValidate: vi.fn() } },
    props: { hostId: "host-a", hostName: "Host A" }, visible: { value: true },
    store: { saveAppProfiles: vi.fn().mockResolvedValue(undefined) }, emit: vi.fn(),
    ElMessage: { error: vi.fn(), success: vi.fn() }, t: (key: string) => key,
  };
  const handlers = new Function("ctx", `with (ctx) { ${code}; return { editProfile, removeProfile, addProfile, saveProfiles }; }`)(ctx);
  return { ctx, handlers };
}

describe("Shared app profile editor", () => {
  it("replaces the original entry when its pattern changes", async () => {
    const { ctx, handlers } = fixture();
    handlers.editProfile(ctx.profiles.value[0], 0);
    ctx.form.stack_pattern = "new";
    await handlers.addProfile();
    expect(ctx.profiles.value).toEqual([entry("new")]);
    expect(ctx.editingIndex.value).toBeNull();
  });

  it.each([0, 1])("merges a renamed entry into an existing pattern (editing index %i)", async (index) => {
    const { ctx, handlers } = fixture([entry("first"), entry("second")]);
    handlers.editProfile(ctx.profiles.value[index], index);
    const target = index === 0 ? "second" : "first";
    ctx.form.stack_pattern = target;
    ctx.form.title = "updated";
    await handlers.addProfile();
    expect(ctx.profiles.value).toEqual([{ ...entry(target), title: "updated" }]);
  });

  it("keeps an absolute icon path when editing and saving an entry", async () => {
    const { ctx, handlers } = fixture([entry("app", "/api/static/icons/app.svg")]);
    handlers.editProfile(ctx.profiles.value[0], 0);
    expect(ctx.form.sourceType).toBe("url");
    await handlers.addProfile();
    expect(ctx.profiles.value[0]!.icon_value).toBe("/api/static/icons/app.svg");
  });

  it("adjusts the edit index when an earlier entry is removed", async () => {
    const { ctx, handlers } = fixture([entry("first"), entry("second")]);
    handlers.editProfile(ctx.profiles.value[1], 1);
    handlers.removeProfile(0);
    ctx.form.stack_pattern = "renamed";
    await handlers.addProfile();
    expect(ctx.profiles.value).toEqual([entry("renamed")]);
  });

  it("leaves entries unchanged when form validation fails", async () => {
    const { ctx, handlers } = fixture();
    ctx.formRef.value.validate.mockRejectedValue(new Error("invalid URL"));
    ctx.form.stack_pattern = "new";
    await handlers.addProfile();
    expect(ctx.profiles.value).toEqual([entry("old")]);
  });

  it("saves for the selected host and emits the refresh only after success", async () => {
    const { ctx, handlers } = fixture();
    ctx.store.saveAppProfiles.mockRejectedValueOnce("save failed");
    await handlers.saveProfiles();
    expect(ctx.visible.value).toBe(true);
    expect(ctx.emit).not.toHaveBeenCalled();
    await handlers.saveProfiles();
    expect(ctx.store.saveAppProfiles).toHaveBeenLastCalledWith("host-a", ctx.profiles.value);
    expect(ctx.visible.value).toBe(false);
    expect(ctx.emit).toHaveBeenCalledWith("saved");
  });
});
