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
    world_brief: "narrator",
    sequence_arc: "arc",
    scenes: [],
    ...extras,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("TopBar", () => {
  it("shows song identity and visual language without independent controls", () => {
    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);

    expect(screen.getByText("blackbird")).toBeInTheDocument();
    expect(screen.getByText(/visual language: stained glass · abstraction 25/i)).toBeInTheDocument();
    expect(screen.queryByText(/^filter:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^abstraction:/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
  });

  it("shows unset visual language as read-only state", () => {
    render(
      <MemoryRouter>
        <TopBar
          song={makeSong({ filter: null, abstraction: null, world_brief: null })}
          onSongUpdate={() => {}}
          onBack={() => {}}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/visual language: unset/i)).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
  });

  it("quality_mode change still opens confirmation without fetching preview-change", async () => {
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy;

    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    const modeSelect = screen.getByRole("combobox") as HTMLSelectElement;
    await userEvent.selectOptions(modeSelect, "final");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/No Gemini calls/i)).toBeInTheDocument();
    expect(screen.getByText(/Instant/i)).toBeInTheDocument();
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    expect(urls.some(u => u.includes("/preview-change"))).toBe(false);
  });
});
