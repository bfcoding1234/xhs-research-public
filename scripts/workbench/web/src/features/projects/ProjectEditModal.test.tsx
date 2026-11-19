import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import type { Project } from '@/types';
import ProjectEditModal from './ProjectEditModal';

const project: Project = {
  id: 12,
  name: '原项目名称',
  slug: 'original-project',
  description: '原项目说明',
  research_type: 'keyword',
  status: 'active',
  config_json: {},
  latest_report_id: null,
  created_at: '',
  updated_at: '',
  archived_at: null,
};

describe('ProjectEditModal', () => {
  it('prefills project information and submits trimmed values', async () => {
    const onSave = vi.fn();
    render(
      <AntApp>
        <ProjectEditModal
          project={project}
          open
          saving={false}
          onCancel={vi.fn()}
          onSave={onSave}
        />
      </AntApp>,
    );

    const name = await screen.findByLabelText('项目名称');
    const description = screen.getByLabelText('项目说明');
    await waitFor(() => expect(name).toHaveValue('原项目名称'));
    expect(description).toHaveValue('原项目说明');

    fireEvent.change(name, { target: { value: '  新项目名称  ' } });
    fireEvent.change(description, { target: { value: '  新项目说明  ' } });
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        name: '新项目名称',
        description: '新项目说明',
      }),
    );
  });

  it('does not submit a blank project name', async () => {
    const onSave = vi.fn();
    render(
      <AntApp>
        <ProjectEditModal
          project={project}
          open
          saving={false}
          onCancel={vi.fn()}
          onSave={onSave}
        />
      </AntApp>,
    );

    const name = await screen.findByLabelText('项目名称');
    fireEvent.change(name, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));

    expect(await screen.findByText('请填写项目名称')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });
});
