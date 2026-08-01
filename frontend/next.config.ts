import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // Pin the workspace root to this project -- a stray lockfile at
    // /Users/akshithm/package-lock.json otherwise makes Next.js guess wrong.
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
