# Chronicle Web

Next.js + TypeScript research workspace. Scaffold is being added in staged commits.

## Prerequisites
Node.js LTS and pnpm.

## Setup
```bash
pnpm install
pnpm --filter @chronicle/web dev
```

The app uses `NEXT_PUBLIC_API_BASE_URL` for the API URL. Do not put private provider secrets in variables prefixed with `NEXT_PUBLIC_`.
