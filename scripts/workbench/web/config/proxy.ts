const target = process.env.XHS_RESEARCH_API_TARGET || 'http://127.0.0.1:4320';

const proxy: Record<
  string,
  Record<string, { target: string; changeOrigin: boolean }>
> = {
  dev: {
    '/api/': { target, changeOrigin: true },
    '/media/': { target, changeOrigin: true },
  },
};

export default proxy;
