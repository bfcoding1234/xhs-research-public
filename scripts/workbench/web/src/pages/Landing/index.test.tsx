import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LandingPage from './index';

vi.mock('@umijs/max', () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
}));

describe('LandingPage', () => {
  it('introduces the research workflow and links to the existing workbench', () => {
    render(<LandingPage />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '不止看见热门，找到内容为什么有效。',
    );
    expect(document.title).toBe('xhs-research｜小红书内容研究工作台');
    expect(screen.getByText('追踪作者的内容脉络')).toBeInTheDocument();
    expect(screen.getByText('读懂图片里的关键信息')).toBeInTheDocument();

    const workbenchLinks = screen.getAllByRole('link', { name: /工作台|开始研究/ });
    expect(workbenchLinks.length).toBeGreaterThan(0);
    for (const link of workbenchLinks) {
      expect(link).toHaveAttribute('href', '/my-projects');
    }
  });

  it('scrolls to capability content without changing the hash route', () => {
    const scrollIntoView = vi.fn();
    const section = document.createElement('section');
    section.id = 'capabilities';
    section.scrollIntoView = scrollIntoView;
    document.body.appendChild(section);

    render(<LandingPage />);
    fireEvent.click(screen.getByRole('button', { name: '看看能做什么' }));

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    section.remove();
  });
});
