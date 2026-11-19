import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ProjectTaskRow } from '@/utils/projectTasks';
import ProjectDeleteAction from './ProjectDeleteAction';

function project(activeTaskCount = 0): ProjectTaskRow {
  return {
    id: 8,
    name: '竞品调研',
    slug: 'project-8',
    description: '',
    research_type: 'mixed',
    status: 'active',
    config_json: {},
    latest_report_id: null,
    created_at: '',
    updated_at: '',
    archived_at: null,
    active_tasks: Array.from({ length: activeTaskCount }, (_, index) => ({ id: `task-${index}` })) as ProjectTaskRow['active_tasks'],
  };
}

describe('ProjectDeleteAction', () => {
  it('requires the complete project name before deletion', async () => {
    const onDelete = vi.fn();
    render(
      <ProjectDeleteAction
        project={project()}
        taskStateUnknown={false}
        mutationPending={false}
        deleting={false}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '删除项目：竞品调研' }));
    expect(await screen.findByText('项目关系和报告会被删除，历史任务转为独立任务；全局帖子与作者会保留。'))
      .toBeInTheDocument();
    const confirmButton = screen.getByRole('button', { name: '删除项目' });
    const nameInput = screen.getByLabelText('请输入完整项目名称以确认：竞品调研');

    expect(confirmButton).toBeDisabled();
    fireEvent.change(nameInput, { target: { value: '竞品' } });
    expect(confirmButton).toBeDisabled();
    expect(screen.getByText('输入内容与项目名称不一致')).toBeInTheDocument();
    fireEvent.change(nameInput, { target: { value: '竞品调研 ' } });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(nameInput, { target: { value: '竞品调研' } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    expect(onDelete).toHaveBeenCalledOnce();
  });

  it.each([
    { taskStateUnknown: true, activeTaskCount: 0 },
    { taskStateUnknown: false, activeTaskCount: 1 },
  ])('blocks deletion when task safety cannot be established', ({ taskStateUnknown, activeTaskCount }) => {
    render(
      <ProjectDeleteAction
        project={project(activeTaskCount)}
        taskStateUnknown={taskStateUnknown}
        mutationPending={false}
        deleting={false}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '删除项目：竞品调研' })).toBeDisabled();
  });
});
