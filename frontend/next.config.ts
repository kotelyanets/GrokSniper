import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow monitor PC to connect without cross-origin warnings on Next.js 16+
  output: 'standalone',
};

export default nextConfig;
