import React from 'react';
import { fmt, kgFmt } from './money';

// Decorative layers only: amounts and actions remain owned by the live CRM.
export function CardSurface() {
  return (
    <>
      <div className="card-surface" aria-hidden="true">
        <span className="satin satin--pearl" />
        <span className="satin satin--dark" />
      </div>
      <span className="border-shimmer" aria-hidden="true" />
      <span className="glint glint--top" aria-hidden="true" />
      <span className="glint glint--bottom" aria-hidden="true" />
    </>
  );
}

export function DashboardMetric({ label, value, icon: Icon, note, weight = false, variant = '' }) {
  return (
    <article className={`stat-card emerald-card ${variant}`}>
      <CardSurface />
      <div className="card-header">
        <h2 className="card-title">{label}</h2>
        <span className="card-icon">
          <Icon aria-hidden="true" />
        </span>
      </div>
      <div className="card-amount">
        <strong className="card-value">{weight ? kgFmt(value) : fmt(value)}</strong>
        <span className="card-unit">{weight ? 'kg' : 'so‘m'}</span>
      </div>
      <p className="card-meta">{note}</p>
    </article>
  );
}
