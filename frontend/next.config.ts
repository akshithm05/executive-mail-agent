import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a minimal, self-contained server bundle (.next/standalone) with
  // only the node_modules actually needed at runtime -- what Dockerfile
  // builds against. See https://nextjs.org/docs/app/api-reference/config/next-config-js/output
  output: "standalone",
  turbopack: {
    // Pin the workspace root to this project -- a stray lockfile at
    // /Users/akshithm/package-lock.json otherwise makes Next.js guess wrong.
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
