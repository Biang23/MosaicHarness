import { expect, test } from "@playwright/test";

test("creates a blueprint from the support template", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("template-support").click();
  await expect(page.getByLabel("System prompt")).toBeVisible();
  await expect(page.getByLabel("Agent inspector").getByText("draft", { exact: true })).toBeVisible();
});

test("equips a workflow through the resource palette", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("template-support").click();
  await page.getByTestId("palette-research-and-cite").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Equip resource" }).click();
  await page.getByRole("tab", { name: "Workflows" }).click();
  await expect(page.getByLabel("Agent inspector").getByText("Optional behavior module", { exact: true })).toBeVisible();
});
