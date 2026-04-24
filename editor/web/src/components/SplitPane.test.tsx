import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import SplitPane from "./SplitPane";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("SplitPane", () => {
  it("renders both panes", () => {
    render(<SplitPane left={<div>LEFT</div>} right={<div>RIGHT</div>} />);
    expect(screen.getByText("LEFT")).toBeInTheDocument();
    expect(screen.getByText("RIGHT")).toBeInTheDocument();
  });

  it("resets to default on double click of the separator", async () => {
    render(<SplitPane left={<div>L</div>} right={<div>R</div>} />);
    const sep = screen.getByRole("separator");
    await userEvent.dblClick(sep);
    const stored = localStorage.getItem("editor.split.lhsPx");
    expect(stored).toContain("480");
  });

  it("starts from a stored lhsPx if present", () => {
    localStorage.setItem("editor.split.lhsPx", JSON.stringify({ version: 1, value: 320 }));
    const { container } = render(<SplitPane left={<div>L</div>} right={<div>R</div>} />);
    const editor = container.querySelector(".editor") as HTMLElement;
    expect(editor.style.getPropertyValue("--lhs-px")).toBe("320px");
  });

  it("falls back to default if stored value is a wrong version", () => {
    localStorage.setItem("editor.split.lhsPx", JSON.stringify({ version: 99, value: 100 }));
    const { container } = render(<SplitPane left={<div>L</div>} right={<div>R</div>} />);
    const editor = container.querySelector(".editor") as HTMLElement;
    expect(editor.style.getPropertyValue("--lhs-px")).toBe("480px");
  });
});
