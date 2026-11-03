/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Browser requests stay on the Chronicle web origin. Vercel forwards them to
  // the API server, avoiding cross-origin CORS failures for authenticated calls.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "https://chronicle-alpha-five.vercel.app/api/v1/:path*"
      }
    ];
  }
};
export default nextConfig;
