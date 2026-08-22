"use client";

import React, { useCallback, useEffect, useId, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Expand,
  ImageIcon,
  Settings,
  X,
} from "lucide-react";
export type Screenshot = {
  src: string;
  alt: string;
  title: string;
  description: string;
  width: number;
  height: number;
};

type ScreenshotGalleryProps = {
  productShots: Screenshot[];
  settingsShots: Screenshot[];
};

function ScreenshotCard({
  shot,
  onOpen,
}: {
  shot: Screenshot;
  onOpen: () => void;
}) {
  return (
    <figure className="gallery-card">
      <button
        type="button"
        onClick={onOpen}
        className="group relative flex min-h-0 w-full flex-1 cursor-zoom-in items-center justify-center bg-muted p-3 text-left"
        aria-label={`View larger: ${shot.title}`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={shot.src}
          alt={shot.alt}
          width={shot.width}
          height={shot.height}
          className="mx-auto h-auto max-h-64 w-full rounded-lg object-contain transition-transform duration-200 group-hover:scale-[1.02]"
        />
        <span className="pointer-events-none absolute bottom-4 right-4 inline-flex items-center gap-1.5 rounded-full bg-[color:var(--dark-ink)] px-2.5 py-1 text-xs font-medium text-[color:var(--paper-bright)] opacity-0 shadow transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
          <Expand className="h-3.5 w-3.5" />
          Expand
        </span>
      </button>
      <figcaption className="space-y-1">
        <h3 className="text-lg font-semibold">{shot.title}</h3>
        <p className="text-sm text-muted-foreground">{shot.description}</p>
      </figcaption>
    </figure>
  );
}

function Lightbox({
  shots,
  index,
  onClose,
  onPrev,
  onNext,
  titleId,
}: {
  shots: Screenshot[];
  index: number;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  titleId: string;
}) {
  const shot = shots[index];
  const hasPrev = index > 0;
  const hasNext = index < shots.length - 1;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowLeft") {
        onPrev();
      } else if (event.key === "ArrowRight") {
        onNext();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, onNext, onPrev]);

  if (!shot) {
    return null;
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90 p-3 sm:p-6"
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute right-3 top-3 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
        aria-label="Close gallery"
      >
        <X className="h-5 w-5" />
      </button>

      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onPrev();
        }}
        disabled={!hasPrev}
        className="absolute left-2 top-1/2 z-10 inline-flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:pointer-events-none disabled:opacity-30 sm:left-4"
        aria-label="Previous screenshot"
      >
        <ChevronLeft className="h-6 w-6" />
      </button>

      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onNext();
        }}
        disabled={!hasNext}
        className="absolute right-2 top-1/2 z-10 inline-flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:pointer-events-none disabled:opacity-30 sm:right-4"
        aria-label="Next screenshot"
      >
        <ChevronRight className="h-6 w-6" />
      </button>

      <div
        className="flex max-h-full w-full max-w-6xl flex-col items-center gap-3"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="relative flex max-h-[min(80vh,900px)] w-full items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={shot.src}
            alt={shot.alt}
            width={shot.width}
            height={shot.height}
            className="max-h-[min(80vh,900px)] w-auto max-w-full rounded-lg object-contain shadow-2xl"
            loading="eager"
          />
        </div>
        <div className="max-w-2xl px-2 text-center text-white">
          <p id={titleId} className="text-lg font-semibold">
            {shot.title}
          </p>
          <p className="mt-1 text-sm text-white/80">{shot.description}</p>
          <p className="mt-2 text-xs text-white/60">
            {index + 1} / {shots.length}
            <span className="mx-2">·</span>
            Esc to close · arrow keys to browse
          </p>
        </div>
      </div>
    </div>
  );
}

export function ScreenshotGallery({
  productShots,
  settingsShots,
}: ScreenshotGalleryProps) {
  const allShots = [...productShots, ...settingsShots];
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const titleId = useId();

  const openAt = useCallback((index: number) => {
    setActiveIndex(index);
  }, []);

  const close = useCallback(() => {
    setActiveIndex(null);
  }, []);

  const showPrev = useCallback(() => {
    setActiveIndex((current) => {
      if (current === null || current <= 0) {
        return current;
      }
      return current - 1;
    });
  }, []);

  const showNext = useCallback(() => {
    setActiveIndex((current) => {
      if (current === null || current >= allShots.length - 1) {
        return current;
      }
      return current + 1;
    });
  }, [allShots.length]);

  return (
    <>
      <section className="mb-14">
        <div className="mb-6 flex items-center gap-2">
          <ImageIcon className="h-5 w-5 text-primary" />
          <h2 className="text-2xl font-bold">Product</h2>
        </div>
        <div className="grid grid-cols-1 items-stretch gap-6 sm:grid-cols-3">
          {productShots.map((shot, index) => (
            <ScreenshotCard
              key={shot.src}
              shot={shot}
              onOpen={() => openAt(index)}
            />
          ))}
        </div>
      </section>

      <section className="mb-14">
        <div className="mb-6 flex items-center gap-2">
          <Settings className="h-5 w-5 text-primary" />
          <h2 className="text-2xl font-bold">Settings</h2>
        </div>
        <p className="mb-6 max-w-3xl text-muted-foreground">
          Every sidebar settings page, from speech model selection through
          advanced whisper.cpp tuning. Click any shot to expand it — images
          follow the site light/dark theme.
        </p>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {settingsShots.map((shot, index) => (
            <ScreenshotCard
              key={shot.src}
              shot={shot}
              onOpen={() => openAt(productShots.length + index)}
            />
          ))}
        </div>
      </section>

      {activeIndex !== null && (
        <Lightbox
          shots={allShots}
          index={activeIndex}
          onClose={close}
          onPrev={showPrev}
          onNext={showNext}
          titleId={titleId}
        />
      )}
    </>
  );
}
