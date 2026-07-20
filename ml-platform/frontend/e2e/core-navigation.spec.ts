import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

test("loads every core authenticated route without redirecting or blank rendering", async ({ page }) => {
  const duplicateApiRequests: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400 && response.url().includes("/api/api/")) {
      duplicateApiRequests.push(`${response.status()} ${response.url()}`);
    }
  });
  await login(page);

  for (const route of [
    "/", "/projects", "/data", "/automl", "/training", "/models",
    "/knowledge", "/knowledge-graph", "/monitor", "/chat", "/compute",
  ]) {
    await page.goto(route);
    await expect(page).toHaveURL(new RegExp(`${route === "/" ? "" : route}$`));
    await expect(page.locator("#root")).toContainText("AI模型训练编排平台");
    await expect(page.locator("#root")).not.toContainText("Something went wrong");
  }

  expect(duplicateApiRequests).toEqual([]);
});
