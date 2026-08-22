import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ScreenshotGallery,
  type Screenshot,
} from "../screenshot-gallery";

const productShots: Screenshot[] = [
  {
    src: "/screenshots/00-transcription.png",
    alt: "Transcription alt",
    title: "Transcription in action",
    description: "Dictate into apps",
    width: 100,
    height: 80,
  },
  {
    src: "/screenshots/02-system-tray.png",
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
    alt: "Speech engine alt",
    title: "Speech Engine",
    description: "Pick a model",
    width: 100,
    height: 160,
  },
];

describe("ScreenshotGallery lightbox", () => {
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
