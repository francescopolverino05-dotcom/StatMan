import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This app sits in a folder of another Next.js project; without this, the build takes the parent as its root.
  turbopack: { root: path.resolve(__dirname) },
};

export default nextConfig;
