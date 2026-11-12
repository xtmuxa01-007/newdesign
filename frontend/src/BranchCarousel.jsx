import React, { Children, useId, useLayoutEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { isTelegramEntry } from './telegram';
import './branch-carousel.css';

const GAP = 15;
const ORIGINAL_MIN_WIDTH = 230;

export function BranchCarousel({ children }) {
  const cards = Children.toArray(children);
  const miniApp = isTelegramEntry();
  const trackRef = useRef(null);
  const trackId = useId();
  const [cardWidth, setCardWidth] = useState(0);
  const [edges, setEdges] = useState({ start: true, end: true });

  useLayoutEffect(() => {
    if (miniApp || cards.length < 2) return;
    const track = trackRef.current;
    const mobile = window.matchMedia('(max-width: 760px)');
    const measure = () => {
      const width = track.clientWidth;
      if (!width) return;
      const columns = mobile.matches
        ? 1
        : Math.min(
            cards.length,
            Math.max(1, Math.floor((width + GAP) / (ORIGINAL_MIN_WIDTH + GAP))),
          );
      const originalWidth = (width - GAP * (columns - 1)) / columns;
      // Keep an entire card readable on narrow screens; desktop cards are 30% wider.
      setCardWidth(Math.min(width, originalWidth * 1.3));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    mobile.addEventListener('change', measure);
    return () => {
      observer.disconnect();
      mobile.removeEventListener('change', measure);
    };
  }, [children, miniApp]);

  useLayoutEffect(() => {
    if (miniApp || cards.length < 2) return;
    const track = trackRef.current;
    const sync = () => {
      const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
      const start = track.scrollLeft <= 1;
      const end = track.scrollLeft >= maximum - 1;
      setEdges((current) =>
        current.start === start && current.end === end ? current : { start, end },
      );
    };
    sync();
    track.addEventListener('scroll', sync, { passive: true });
    return () => track.removeEventListener('scroll', sync);
  }, [children, cardWidth, miniApp]);

  if (miniApp || cards.length < 2) return <div className="branch-cards">{cards}</div>;

  function scroll(direction) {
    const track = trackRef.current;
    const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 'instant'
      : 'smooth';
    const step = (track.firstElementChild?.getBoundingClientRect().width || cardWidth) + GAP;
    const left =
      direction === 'start'
        ? 0
        : direction === 'end'
          ? track.scrollWidth - track.clientWidth
          : track.scrollLeft + direction * step;
    track.scrollTo({ left, behavior });
  }

  function onKeyDown(event) {
    if (event.target !== event.currentTarget) return;
    const direction = { ArrowLeft: -1, ArrowRight: 1, Home: 'start', End: 'end' }[event.key];
    if (direction === undefined) return;
    event.preventDefault();
    scroll(direction);
  }

  return (
    <div
      className="branch-carousel"
      role="region"
      aria-roledescription="karusel"
      aria-label="Filiallar holati"
    >
      <div
        className="branch-carousel-track"
        role="group"
        ref={trackRef}
        id={trackId}
        tabIndex={0}
        aria-label="Filial kartalari"
        onKeyDown={onKeyDown}
        style={cardWidth ? { '--branch-card-width': `${cardWidth}px` } : undefined}
      >
        {cards}
      </div>
      <div className="branch-carousel-controls">
        <button
          type="button"
          className="branch-carousel-button"
          aria-label="Oldingi filial"
          aria-controls={trackId}
          disabled={edges.start}
          onClick={() => scroll(-1)}
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="branch-carousel-button"
          aria-label="Keyingi filial"
          aria-controls={trackId}
          disabled={edges.end}
          onClick={() => scroll(1)}
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
