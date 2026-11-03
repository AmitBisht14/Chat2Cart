import { expect, it } from "vitest";
import { SERVICE_NAME } from "../src/index.js";

it("names_the_service", () => {
  expect(SERVICE_NAME).toBe("chat2cart-listener");
});
