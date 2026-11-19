import { defineConfig } from '@umijs/max';
import defaultSettings from './defaultSettings';
import proxy from './proxy';
import routes from './routes';

const { UMI_ENV = 'dev' } = process.env;

export default defineConfig({
  hash: true,
  esbuildMinifyIIFE: true,
  history: { type: 'hash' },
  publicPath: '/',
  routes,
  title: '小红书个人工作台',
  favicons: ['/logo.svg'],
  fastRefresh: true,
  routePrefetch: {},
  manifest: {},
  model: {},
  initialState: {},
  layout: {
    locale: false,
    ...defaultSettings,
  },
  locale: {
    default: 'zh-CN',
    antd: true,
    baseNavigator: false,
  },
  antd: {
    appConfig: {},
    configProvider: {
      variant: 'filled',
      theme: {
        cssVar: true,
        token: {
          colorPrimary: '#1677ff',
          colorSuccess: '#52c41a',
          colorWarning: '#faad14',
          colorError: '#ff4d4f',
          borderRadius: 6,
          fontSize: 14,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
      },
    },
  },
  reactQuery: {},
  proxy: proxy[UMI_ENV],
});
