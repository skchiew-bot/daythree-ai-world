import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorldErrorBoundary, WorldUnavailable } from "./WorldErrorBoundary";

describe("WorldErrorBoundary", () => {
  it("switches to the failed state when a child throws", () => {
    expect(WorldErrorBoundary.getDerivedStateFromError()).toEqual({ failed: true });
  });

  it("renders its children while nothing has failed", () => {
    const html = renderToStaticMarkup(createElement(WorldErrorBoundary, null, createElement("p", null, "scene")));

    expect(html).toBe("<p>scene</p>");
  });

  it("shows an accessible alert instead of the scene", () => {
    const html = renderToStaticMarkup(createElement(WorldUnavailable));

    expect(html).toContain('role="alert"');
    expect(html).toContain("The 3D view could not start on this device");
  });
});
