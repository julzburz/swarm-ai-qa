import type { NextConfig } from "next";

const controlPlane = (
  process.env.SWARM_CONTROL_PLANE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/control-plane/:path*",
        destination: `${controlPlane}/:path*`,
      },
    ];
  },
};

export default nextConfig;
