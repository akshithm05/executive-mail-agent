# syntax=docker/dockerfile:1.7

# ---- Dependencies -------------------------------------------------------------
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# BuildKit cache mount: npm's download cache persists across builds without
# ending up in any image layer -- faster rebuilds when only source changed.
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# ---- Builder --------------------------------------------------------------
# Builds the standalone server bundle (next.config.ts: output: "standalone")
# -- a minimal, self-contained runtime with only the node_modules actually
# needed, so the runtime stage never needs a full npm install.
FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not
# read at container start -- must be supplied here, not just at `docker run`.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

# ---- Runtime ----------------------------------------------------------------
FROM node:22-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system app && useradd --system --gid app --create-home app

# The standalone output already contains a minimal node_modules and a
# server.js entrypoint -- static assets and public/ are copied in
# separately since `output: "standalone"` deliberately excludes them.
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public

USER app

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
