// The page's building blocks. Colors are the tokens of styles.css (light and dark).

const BUTTON = {
  primary: "bg-accent text-accent-ink border-transparent",
  ghost: "bg-ink/5 text-ink border-line hover:bg-ink/10",
  danger: "bg-no text-white border-transparent",
  ok: "bg-ok text-white border-transparent",
};
const SIZE = { md: "px-4 py-2 text-[15px]", sm: "px-3 py-1.5 text-sm" };

// A button, or a link that looks like one when href is given.
export function Button({ variant = "primary", size = "md", href, className = "", ...rest }) {
  const classes = `inline-flex cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border font-semibold no-underline transition hover:brightness-105 hover:no-underline disabled:cursor-progress disabled:opacity-55 ${BUTTON[variant]} ${SIZE[size]} ${className}`;
  return href ? <a href={href} className={classes} {...rest} /> : <button type="button" className={classes} {...rest} />;
}

const BADGE = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  no: "bg-no-soft text-no",
  info: "bg-info-soft text-info",
  accent: "bg-accent-soft text-accent",
  "": "bg-code text-muted",
};

export function Badge({ kind = "", dot = false, className = "", children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE[kind] ?? BADGE[""]} ${className}`}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Card({ className = "", children }) {
  return <section className={`rounded-xl border border-line bg-card p-5 shadow-card backdrop-blur-md ${className}`}>{children}</section>;
}

// A colored box with a short message: kind ok, warn, no, info or accent
export function Notice({ kind = "info", title, children }) {
  const tone = { ok: "bg-ok-soft", warn: "bg-warn-soft", no: "bg-no-soft", info: "bg-info-soft", accent: "bg-accent-soft", glass: "border border-white/10 bg-glass/45 backdrop-blur-xl" }[kind];
  return (
    <div className={`rounded-lg px-4 py-3.5 ${tone}`}>
      {title && <h3 className="mb-1 font-semibold">{title}</h3>}
      {children}
    </div>
  );
}

// back arrow above a page title
export const BackLink = ({ href, label }) => (
  <a href={href} aria-label={label} title={label} className="mb-3 inline-block text-ink transition hover:text-accent hover:no-underline">
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5M11 18l-6-6 6-6" />
    </svg>
  </a>
);

export function PageHead({ title, children, actions, size = "text-3xl" }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className={`${size} font-semibold`}>{title}</h1>
        {children && <p className="mt-1 text-muted">{children}</p>}
      </div>
      {actions}
    </div>
  );
}

export const inputClass = "w-full rounded-lg border border-line bg-panel px-3 py-2 text-ink";

export function Field({ id, label, children }) {
  return (
    <div className="mt-3 first:mt-0">
      <label htmlFor={id} className="mb-1 block text-[13px] font-medium text-muted">{label}</label>
      {children}
    </div>
  );
}
