import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SongBrowser from "./SongBrowser";
import type { Song } from "../types";

function makeSong(partial: Partial<Song> & { slug: string }): Song {
  return {
    slug: partial.slug,
    audio_path: `/Users/x/music/${partial.slug}.wav`,
    duration_s: 210,
    size_bytes: 44_000_000,
    filter: "stained glass",
    abstraction: 25,
    quality_mode: "draft",
    status: {
      transcription: "done",
      world_brief: "done",
      storyboard: "done",
      keyframes_done: 5,
      keyframes_total: 10,
      clips_done: 0,
      clips_total: 10,
      final: "empty",
      ...partial.status,
    },
    ...partial,
  };
}

function stubFetch(songs: Song[]) {
  const spy = vi.fn().mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({ songs }),
  } as Response);
  // @ts-expect-error override global fetch
  globalThis.fetch = spy;
  return spy;
}

function renderBrowser() {
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <MemoryRouter>
        <SongBrowser />
      </MemoryRouter>
    </SWRConfig>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("SongBrowser", () => {
  it("renders songs fetched from /api/songs", async () => {
    const spy = stubFetch([
      makeSong({ slug: "blackbird" }),
      makeSong({ slug: "chronophobia" }),
    ]);
    renderBrowser();
    await screen.findByText("blackbird");
    expect(screen.getByText("chronophobia")).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith("/api/songs");
  });

  it("renders empty state when zero songs", async () => {
    stubFetch([]);
    renderBrowser();
    await screen.findByText(/no songs found/i);
    expect(screen.getByRole("button", { name: /scan music folder/i })).toBeInTheDocument();
  });

  it("persists the list/grid toggle via localStorage", async () => {
    stubFetch([makeSong({ slug: "blackbird" })]);
    renderBrowser();
    await screen.findByText("blackbird");

    const gridTab = screen.getByRole("tab", { name: /grid/i });
    await userEvent.click(gridTab);
    expect(gridTab).toHaveAttribute("aria-selected", "true");
    expect(localStorage.getItem("editor.browser.view")).toContain("grid");
  });

  it("renders status-strip with kf progress in 'progress' class when partial", async () => {
    stubFetch([makeSong({ slug: "blackbird" })]);
    renderBrowser();
    const row = await screen.findByText("blackbird");
    const parent = row.closest(".song-row")!;
    const kf = within(parent as HTMLElement).getByText(/kf 5\/10/);
    expect(kf).toHaveClass("progress");
  });
});
