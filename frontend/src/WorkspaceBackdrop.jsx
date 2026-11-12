import React from 'react';
import './workspace-backdrop.css';

const contours = Array.from({ length: 21 }, (_, index) => {
  const offset = (index - 10) * 44;
  return `M -180 ${410 + offset} C 110 ${100 + offset}, 330 ${650 + offset}, 650 ${330 + offset} S 1110 ${70 + offset}, 1580 ${350 + offset}`;
});
const motes = [
  [7, 21, 0],
  [23, 47, -4],
  [41, 12, -9],
  [58, 38, -2],
  [79, 19, -7],
  [94, 57, -12],
  [12, 79, -6],
  [37, 91, -1],
  [66, 71, -11],
  [86, 89, -5],
];

// One decorative layer sits behind every page; colors come from the active theme.
export function WorkspaceBackdrop() {
  return (
    <div className="workspace-atmosphere" aria-hidden="true">
      <div className="workspace-aura" />
      <div className="workspace-grain" />
      <svg
        className="workspace-contours"
        viewBox="0 0 1400 1000"
        preserveAspectRatio="xMidYMid slice"
        focusable="false"
      >
        <defs>
          <linearGradient id="workspace-contour-ink" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" className="contour-stop-clear" />
            <stop offset="0.22" className="contour-stop-color" />
            <stop offset="0.55" className="contour-stop-light" />
            <stop offset="0.78" className="contour-stop-gold" />
            <stop offset="1" className="contour-stop-clear" />
          </linearGradient>
        </defs>
        <g className="workspace-contour-lines">
          {contours.map((path, index) => (
            <path key={index} d={path} />
          ))}
        </g>
        <g className="workspace-light-trails">
          {[5, 10, 15].map((index, position) => (
            <path
              key={index}
              d={contours[index]}
              style={{ '--trail-delay': `${position * -13}s` }}
            />
          ))}
        </g>
      </svg>
      {motes.map(([left, top, delay], index) => (
        <span
          key={index}
          className="workspace-light-mote"
          style={{
            left: `${left}%`,
            top: `${top}%`,
            '--mote-delay': `${delay}s`,
          }}
        />
      ))}
    </div>
  );
}
