import { MoreOutlined } from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link } from '@umijs/max';
import { Tag } from 'antd';
import type { ReactNode } from 'react';
import defaultSettings from '../config/defaultSettings';
import AppErrorBoundary from './components/AppErrorBoundary';
import { groupLowFrequencyMenuItems } from './utils/menu';
import { postDetailMenuPath } from './utils/postNavigation';
import './global.css';

function menuLocation() {
  if (typeof window === 'undefined') return undefined;

  const route = window.location.hash.replace(/^#/, '') || '/';
  const queryStart = route.indexOf('?');
  const pathname = queryStart === -1 ? route : route.slice(0, queryStart);
  const search = queryStart === -1 ? '' : route.slice(queryStart);
  const sourcePath = pathname.startsWith('/posts/') ? postDetailMenuPath(search) : undefined;

  return { pathname: sourcePath ?? pathname };
}

function BrandTitle() {
  return (
    <span className="brand-title">
      <span>小红书个人工作台</span>
      <Tag className="brand-environment-tag" color="blue">
        开发版
      </Tag>
    </span>
  );
}

export const layout: RunTimeLayoutConfig = () => ({
  ...defaultSettings,
  location: menuLocation(),
  menuHeaderRender: (logo, _title, props) =>
    props?.collapsed ? (
      logo
    ) : (
      <span className="brand-lockup">
        {logo}
        <BrandTitle />
      </span>
    ),
  menuDataRender: (menuData) => groupLowFrequencyMenuItems(menuData, <MoreOutlined />),
  menuItemRender: (item, dom) =>
    item.path ? (
      <Link to={item.path} prefetch>
        {dom}
      </Link>
    ) : (
      dom
    ),
  footerRender: false,
});

export function rootContainer(container: ReactNode) {
  return <AppErrorBoundary>{container}</AppErrorBoundary>;
}
