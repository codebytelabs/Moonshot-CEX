import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin turbopack root to THIS directory to prevent workspace
  // root detection from picking up the parent lockfile.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
