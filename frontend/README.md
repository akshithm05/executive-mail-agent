# AEEA Frontend

The dashboard for the AI Executive Email Assistant — Next.js 16 (App
Router) + React 19.2, entirely client-rendered, talking to the
[backend API](../backend/) via cookies + a typed `fetch` client.

See the repo root's [`docs/`](../docs/) for architecture, deployment, and
user documentation; see [`docs/DEVELOPER_GUIDE.md`](../docs/DEVELOPER_GUIDE.md)
for the fuller day-to-day developer workflow across both halves of the
monorepo. This file covers just the frontend specifics.

> **Note for AI coding agents**: this Next.js version has breaking API/
> convention changes from most training data — see [`AGENTS.md`](AGENTS.md)
> before generating Next.js-specific code.

## Setup

```bash
npm install
npm run dev
# http://localhost:3000
```

Requires the backend running and reachable at `NEXT_PUBLIC_API_BASE_URL`
(defaults to `http://localhost:8000/api/v1`) — see
[`../backend/README.md`](../backend/README.md) or
[`../docs/DEVELOPER_GUIDE.md`](../docs/DEVELOPER_GUIDE.md) to get it running.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Start the dev server with hot reload. |
| `npm run build` | Production build. |
| `npm start` | Serve the production build. |
| `npm run lint` | ESLint (`eslint-config-next`, flat config). |
| `npx tsc --noEmit` | Strict TypeScript type check. |
| `npm test` | Run the Vitest suite once. |
| `npm run test:watch` | Vitest in watch mode. |

## Project layout

```
src/
├── app/            # App Router pages — one per top-level nav item
├── components/
│   ├── dashboard/   # Dashboard-specific widgets (stat tiles, charts, cards)
│   ├── shell/       # App shell: nav, theme toggle
│   ├── shared/      # Cross-page primitives: empty/error states, animated number, skeletons
│   ├── drafts/       # Draft-reply review card
│   └── ui/          # shadcn/ui design-system primitives
├── lib/
│   ├── api.ts        # Typed fetch client — every backend call goes through here
│   ├── auth.tsx       # AuthGate + useCurrentUser (session-gated app shell)
│   ├── types.ts       # API response shapes, hand-kept in sync with the backend schemas
│   ├── category-meta.ts  # Email-category display labels/colors, fixed order for chart color safety
│   └── utils.ts       # `cn()` class-name helper
└── hooks/
    └── use-async.ts   # The one hook every page's data-fetching goes through
```

## Testing

Vitest + React Testing Library, set up per the [official Next.js Vitest guide](https://nextjs.org/docs/app/guides/testing/vitest)
(`vitest.config.mts`), with real-boundary fakes rather than mocking this
codebase's own components/hooks — see
[`../docs/DEVELOPER_GUIDE.md` §5](../docs/DEVELOPER_GUIDE.md#5-test-philosophy--read-this-before-adding-a-mock)
for the philosophy shared with the backend suite. Tests live alongside the
code they cover, in `__tests__/` directories.

## Authentication

There's no client-side-only auth state: `AuthGate` (`src/lib/auth.tsx`)
gates the entire app behind a real `GET /auth/me` check against the backend
on load. Every mutating request automatically echoes the CSRF cookie the
backend issues at login back as an `X-CSRF-Token` header — see
`src/lib/auth.tsx` and [`../docs/ARCHITECTURE.md` §5](../docs/ARCHITECTURE.md#5-authentication--session-model).
