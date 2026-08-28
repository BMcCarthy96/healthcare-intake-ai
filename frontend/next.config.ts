import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.NEXT_DISABLE_STANDALONE === "true" ? undefined : "standalone",
  distDir: process.env.NEXT_DIST_DIR || ".next",
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  env: {
    NEXT_PUBLIC_GIT_SHA: process.env.NEXT_PUBLIC_GIT_SHA || process.env.VERCEL_GIT_COMMIT_SHA || "local",
    NEXT_PUBLIC_BUILD_TIME: process.env.NEXT_PUBLIC_BUILD_TIME || new Date().toISOString(),
  },
};

export default nextConfig;
