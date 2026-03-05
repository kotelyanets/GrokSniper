import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow monitor PC to connect without cross-origin warnings on Next.js 16+
  // @ts-ignore - allowedDevOrigins is valid in Turbopack/Next15+ but sometimes missing in local types
  experimental: {
    allowedDevOrigins: ["192.168.1.140", "192.168.1.159", "localhost"],
  },
};

export default nextConfig;
