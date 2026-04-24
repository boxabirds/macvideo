import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import TopBar from "./TopBar";
import type { SongDetail } from "../types";

function makeSong(extras: Partial<SongDetail> = {}): SongDetail {
  return {
    slug: "blackbird",
    audio_path: "/x/music/blackbird.wav",
    duration_s: 220,
    size_bytes: 1_000_000,
    filter: "stained glass",
    abstraction: 25,
    quality_mode: "draft",
    world_brief: "narrator", sequence_arc: "arc",
    scenes: [],
    ...extras,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("TopBar", () => {
  it("shows the song slug and the current filter + abstraction + mode", () => {
    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    expect(screen.getByText("blackbird")).toBeInTheDocument();
    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect(selects[0]!.value).toBe("stained glass");
  });

  it("opens a confirmation dialog when filter changes and does not mutate until confirmed", async () => {
    const onUpdate = vi.fn();
    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={onUpdate} onBack={() => {}} /></MemoryRouter>);
    const selects = screen.getAllByRole("combobox");
    const filterSelect = selects[0] as HTMLSelectElement;
    await userEvent.selectOptions(filterSelect, "charcoal");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("cancelling the dialog leaves the song unchanged", async () => {
    const onUpdate = vi.fn();
    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={onUpdate} onBack={() => {}} /></MemoryRouter>);
    const filterSelect = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
    await userEvent.selectOptions(filterSelect, "charcoal");
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
