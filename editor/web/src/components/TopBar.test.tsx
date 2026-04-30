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

  it("filter-change dialog fetches preview estimate from /preview-change", async () => {
    const previewResponse = {
      from: { filter: "stained glass", abstraction: 25 },
      to: { filter: "charcoal", abstraction: null },
      scope: {
        will_regen_world_brief: true, will_regen_storyboard: true,
        scenes_with_new_prompts: 69, keyframes_to_generate: 69,
        clips_marked_stale: 65, clips_deleted: 0,
      },
      estimate: {
        gemini_calls: 140, estimated_usd: 3.5,
        estimated_seconds: 1500, confidence: "high",
      },
      would_conflict_with: null,
    };
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => previewResponse,
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    const filterSelect = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
    await userEvent.selectOptions(filterSelect, "charcoal");
    // Dialog opens; preview-change fetch fires.
    await new Promise(r => setTimeout(r, 20));
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    expect(urls.some(u => u.includes("/preview-change"))).toBe(true);
    // Estimate renders in the dialog.
    await new Promise(r => setTimeout(r, 20));
    expect(screen.getByText(/140 Gemini calls/)).toBeInTheDocument();
    expect(screen.getByText(/\$3\.50/)).toBeInTheDocument();
  });

  it("opens a cosmetic confirmation on quality_mode change without fetching preview-change", async () => {
    const fetchSpy = vi.fn();
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    const modeSelect = screen.getAllByRole("combobox")[2] as HTMLSelectElement;
    await userEvent.selectOptions(modeSelect, "final");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // The cosmetic branch copy is rendered.
    expect(screen.getByText(/No Gemini calls/i)).toBeInTheDocument();
    expect(screen.getByText(/Instant/i)).toBeInTheDocument();
    // Preview-change fetch MUST NOT fire for quality_mode changes.
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    expect(urls.some(u => u.includes("/preview-change"))).toBe(false);
  });

  it("fresh-song filter pick shows 'Set filter' setup modal — no destructive copy, no preview-change fetch", async () => {
    const fetchSpy = vi.fn();
    // @ts-expect-error
    globalThis.fetch = fetchSpy;
    const fresh = makeSong({
      filter: null, abstraction: null,
      world_brief: null, sequence_arc: null, scenes: [],
    });
    render(<MemoryRouter><TopBar song={fresh} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0] as HTMLSelectElement, "charcoal");
    expect(screen.getByRole("heading", { name: /set filter/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /confirm filter change/i })).not.toBeInTheDocument();
    // Vacuous "0 …" lines from the destructive modal must NOT appear.
    expect(screen.queryByText(/will be marked stale/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Estimated time/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/keyframes/i)).not.toBeInTheDocument();
    // Confirm button reads "Set filter", not "Apply change".
    expect(screen.getByRole("button", { name: /set filter/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply change/i })).not.toBeInTheDocument();
    // No backend call wasted on a fresh-setup estimate.
    await new Promise(r => setTimeout(r, 30));
    const urls = fetchSpy.mock.calls.map(c => c[0] as string);
    expect(urls.some(u => u.includes("/preview-change"))).toBe(false);
  });

  it("abstraction change shows 'Confirm abstraction change' modal", async () => {
    const song = makeSong();
    render(<MemoryRouter><TopBar song={song} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    await userEvent.selectOptions(screen.getAllByRole("combobox")[1] as HTMLSelectElement, "75");
    expect(screen.getByRole("heading", { name: /confirm abstraction change/i })).toBeInTheDocument();
  });

  it("disables confirm when preview-change reports a conflict", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        from: { filter: "stained glass", abstraction: 25 },
        to: { filter: "charcoal", abstraction: null },
        scope: {
          will_regen_world_brief: true, will_regen_storyboard: true,
          scenes_with_new_prompts: 0, keyframes_to_generate: 0,
          clips_marked_stale: 0, clips_deleted: 0,
        },
        estimate: {
          gemini_calls: 2, estimated_usd: 0.01,
          estimated_seconds: 4, confidence: "high",
        },
        would_conflict_with: { run_id: 42, reason: "a chain is already running" },
      }),
    } as Response);
    // @ts-expect-error
    globalThis.fetch = fetchSpy;

    render(<MemoryRouter><TopBar song={makeSong()} onSongUpdate={() => {}} onBack={() => {}} /></MemoryRouter>);
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0] as HTMLSelectElement, "charcoal");
    await new Promise(r => setTimeout(r, 30));
    const confirmBtn = screen.getByRole("button", { name: /apply change/i });
    expect(confirmBtn).toBeDisabled();
  });
});
