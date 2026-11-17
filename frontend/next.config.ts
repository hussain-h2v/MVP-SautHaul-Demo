import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  async rewrites() {
    const target = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};

export default withNextIntl(nextConfig);
