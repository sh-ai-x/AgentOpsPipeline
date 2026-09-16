/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Talk to the FastAPI server running on 127.0.0.1:8000 from the browser.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000") + "/:path*",
      },
    ];
  },
};

export default nextConfig;
