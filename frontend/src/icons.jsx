// Crisp, consistent line icons (20×20, currentColor stroke) for the app shell — no external icon
// dependency, so nothing leaves the origin and the strict CSP stays intact.
const PATHS = {
  home: <><path d="M3 9.7 10 3.5l7 6.2" /><path d="M5.2 8.8V16.5h9.6V8.8" /></>,
  compass: <><circle cx="10" cy="10" r="7.3" /><path d="M13.2 6.8 11 11l-4.2 2.2L9 9z" /></>,
  signal: <><path d="M10 15.6v-2.4" /><path d="M7 12.7a4.4 4.4 0 0 1 6 0" /><path d="M4.7 10.4a7.7 7.7 0 0 1 10.6 0" /><circle cx="10" cy="15.7" r=".5" /></>,
  sparkles: <><path d="M9.6 3.7 11 8l4.3 1.4L11 10.8 9.6 15 8.2 10.8 4 9.4 8.2 8z" /><path d="M15.2 3.4v2.2M16.3 4.5h-2.2" /></>,
  trending: <><path d="M3.6 13.4 8 9l3 2.7 5.4-5.9" /><path d="M13.4 5.2h3.1v3" /></>,
  crypto: <><circle cx="10" cy="10" r="7.3" /><path d="M8.2 6.4v7.2M8.2 6.4h3.3a1.8 1.8 0 0 1 0 3.6H8.2m0 0h3.6a1.8 1.8 0 0 1 0 3.6H8.2" /></>,
  filter: <><path d="M3.6 5h12.8l-5 5.8V15l-2.8 1.4v-6.6z" /></>,
  journal: <><rect x="5.3" y="3.3" width="9.4" height="13.4" rx="1.6" /><path d="M8 3.3v13.4" /><path d="M10.4 7h2.6M10.4 10h2.6" /></>,
  briefcase: <><rect x="3.4" y="6.6" width="13.2" height="8.6" rx="1.6" /><path d="M7 6.6V5.4A1.6 1.6 0 0 1 8.6 3.8h2.8A1.6 1.6 0 0 1 13 5.4v1.2" /><path d="M3.4 10.3h13.2" /></>,
  star: <><path d="M10 3.5l2 4.2 4.6.7-3.3 3.2.8 4.6L10 14.1l-4.1 2.1.8-4.6L3.4 8.4l4.6-.7z" /></>,
  bell: <><path d="M6.3 8.4a3.7 3.7 0 0 1 7.4 0c0 3.7 1.4 4.8 1.4 4.8H4.9s1.4-1.1 1.4-4.8z" /><path d="M8.6 15.3a1.6 1.6 0 0 0 2.8 0" /></>,
  users: <><circle cx="8" cy="7.8" r="2.4" /><path d="M3.9 15.5a4.2 4.2 0 0 1 8.2 0" /><path d="M13 5.7a2.4 2.4 0 0 1 0 4.2" /><path d="M14.3 15.5a4.2 4.2 0 0 0-1.8-3.4" /></>,
  news: <><rect x="3.9" y="3.7" width="12.2" height="12.6" rx="1.6" /><path d="M6.6 7h6.8M6.6 10h6.8M6.6 13h4.4" /></>,
  calendar: <><rect x="3.7" y="4.6" width="12.6" height="11.7" rx="1.6" /><path d="M3.7 8h12.6M7 3.4v2.4M13 3.4v2.4" /></>,
  book: <><path d="M10 5.5S8.2 4.2 4.5 4.2v9.6c3.7 0 5.5 1.3 5.5 1.3M10 5.5s1.8-1.3 5.5-1.3v9.6c-3.7 0-5.5 1.3-5.5 1.3z" /></>,
  target: <><circle cx="10" cy="10" r="6.7" /><circle cx="10" cy="10" r="3.3" /><circle cx="10" cy="10" r=".6" /></>,
  shield: <><path d="M10 3.3l5.6 2v4.3c0 3.8-2.5 5.6-5.6 6.6-3.1-1-5.6-2.8-5.6-6.6V5.3z" /><path d="M7.7 10l1.6 1.6 3.2-3.3" /></>,
  layers: <><path d="M10 3.5l6.5 3.2L10 9.9 3.5 6.7z" /><path d="M3.5 10.1 10 13.3l6.5-3.2" /></>,
  search: <><circle cx="8.8" cy="8.8" r="5.1" /><path d="m12.6 12.6 3.8 3.8" /></>,
  menu: <><path d="M3.5 6h13M3.5 10h13M3.5 14h13" /></>,
  logout: <><path d="M8 3.9H5.3A1.6 1.6 0 0 0 3.7 5.5v9A1.6 1.6 0 0 0 5.3 16.1H8" /><path d="m12 13 3-3-3-3M15 10H7.4" /></>,
};

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.55" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name] || PATHS.home}
    </svg>
  );
}
