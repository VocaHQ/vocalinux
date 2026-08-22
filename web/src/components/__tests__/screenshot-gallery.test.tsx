import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ScreenshotGallery,
  type Screenshot,
} from "../screenshot-gallery";

const productShots: Screenshot[] = [
  {
    src: "/screenshots/00-transcription.png",
    srcDark: "/screenshots/dark/00-transcription.png",
    alt: "Transcription alt",
    title: "Transcription in action",
    description: "Dictate into apps",
    width: 100,
    height: 80,
  },
  {
    src: "/screenshots/02-system-tray.png",
    srcDark: "/screenshots/dark/02-system-tray.png",
    alt: "Tray alt",
    title: "System tray",
    description: "Tray states",
    width: 100,
    height: 80,
  },
];

const settingsShots: Screenshot[] = [
  {
    src: "/screenshots/settings-speech-engine.png",
    srcDark: "/screenshots/dark/settings-speech-engine.png",
    alt: "Speech engine alt",
    title: "Speech Engine",
    description: "Pick a model",
    width: 100,
    height: 160,
  },
];

function mockColorScheme(dark: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = {
    matches: dark,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.add(listener);
    },
    removeEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => {
      listeners.delete(listener);
    },
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
    emit(next: boolean) {
      media.matches = next;
      const event = { matches: next } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
  window.matchMedia = jest.fn().mockImplementation((query: string) => {
    if (query.includes("prefers-color-scheme: dark")) return media;
    return { ...media, matches: false, addEventListener: jest.fn() };
  });
  return media;
}

describe("ScreenshotGallery lightbox", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockColorScheme(false);
  });

  it("defaults to the browser color scheme before any override", async () => {
    mockColorScheme(true);
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(
      document.querySelector(
        'img.is-on[src="/screenshots/dark/00-transcription.png"]',
      ),
    ).not.toBeNull();
  });

  it("follows the browser scheme until the visitor flips the switch", async () => {
    const media = mockColorScheme(true);
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    act(() => {
      media.emit(false);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    act(() => {
      media.emit(false);
    });
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(sessionStorage.getItem("vocalinux-shot-appearance")).toBe("dark");
  });

  it("restores a tab override from sessionStorage", async () => {
    sessionStorage.setItem("vocalinux-shot-appearance", "dark");
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
  });

  it("flips between light and dark app shots without changing the page theme", async () => {
    const user = userEvent.setup();
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );

    const lightBtn = screen.getByRole("button", { name: "Light" });
    const darkBtn = screen.getByRole("button", { name: "Dark" });
    expect(lightBtn).toHaveAttribute("aria-pressed", "true");
    expect(darkBtn).toHaveAttribute("aria-pressed", "false");

    await user.click(darkBtn);
    expect(darkBtn).toHaveAttribute("aria-pressed", "true");
    expect(lightBtn).toHaveAttribute("aria-pressed", "false");
    expect(
      document.querySelector(
        'img.is-on[src="/screenshots/dark/settings-speech-engine.png"]',
      ),
    ).not.toBeNull();
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("opens an expanded gallery view when a screenshot is clicked", async () => {
    const user = userEvent.setup();
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "View larger: Speech Engine" }),
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // Settings shot is third overall (index 2 -> 3/3)
    expect(within(dialog).getByText(/3 \/ 3/)).toBeInTheDocument();
    const speechImgs = within(dialog).getAllByAltText("Speech engine alt");
    expect(speechImgs.length).toBe(1);
    expect(speechImgs[0]).toHaveAttribute(
      "src",
      "/screenshots/settings-speech-engine.png",
    );
    expect(within(dialog).getByText("Speech Engine")).toBeInTheDocument();
  });

  it("navigates with next/prev controls and closes with Escape", async () => {
    const user = userEvent.setup();
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "View larger: Transcription in action",
      }),
    );

    let dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/1 \/ 3/)).toBeInTheDocument();
    expect(
      within(dialog).getAllByAltText("Transcription alt").length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Next screenshot" }));
    dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/2 \/ 3/)).toBeInTheDocument();
    expect(within(dialog).getAllByAltText("Tray alt").length).toBeGreaterThan(0);

    await user.click(
      screen.getByRole("button", { name: "Previous screenshot" }),
    );
    dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/1 \/ 3/)).toBeInTheDocument();
    expect(
      within(dialog).getAllByAltText("Transcription alt").length,
    ).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("supports keyboard arrow navigation while open", async () => {
    const user = userEvent.setup();
    render(
      <ScreenshotGallery
        productShots={productShots}
        settingsShots={settingsShots}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "View larger: Transcription in action",
      }),
    );

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(
      within(screen.getByRole("dialog")).getAllByAltText("Tray alt").length,
    ).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(
      within(screen.getByRole("dialog")).getAllByAltText("Speech engine alt")
        .length,
    ).toBeGreaterThan(0);

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(
      within(screen.getByRole("dialog")).getAllByAltText("Tray alt").length,
    ).toBeGreaterThan(0);
  });
});
