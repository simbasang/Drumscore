import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the production container (frontend/Dockerfile).
  output: "standalone",
};

export default nextConfig;
