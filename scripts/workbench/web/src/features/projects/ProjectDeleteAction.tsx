import { DeleteOutlined } from '@ant-design/icons';
import { Button, Form, Input, Modal, Typography } from 'antd';
import { useState } from 'react';
import type { ProjectTaskRow } from '@/utils/projectTasks';
import { canDeleteProject } from '@/utils/projectTasks';

interface ProjectDeleteActionProps {
  project: Pick<ProjectTaskRow, 'id' | 'name' | 'active_tasks'>;
  taskStateUnknown: boolean;
  mutationPending: boolean;
  deleting: boolean;
  onDelete: () => void;
  open?: boolean;
  hideTrigger?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export default function ProjectDeleteAction({
  project,
  taskStateUnknown,
  mutationPending,
  deleting,
  onDelete,
  open: controlledOpen,
  hideTrigger = false,
  onOpenChange,
}: ProjectDeleteActionProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = (next: boolean) => {
    setInternalOpen(next);
    onOpenChange?.(next);
  };
  const [confirmationName, setConfirmationName] = useState('');
  const taskSafetyConfirmed = canDeleteProject({
    taskStateUnknown,
    activeTaskCount: project.active_tasks.length,
    confirmationMatches: true,
  });
  const confirmationMatches = confirmationName === project.name;
  const deleteAllowed = taskSafetyConfirmed && confirmationMatches;
  const triggerDisabled = !taskSafetyConfirmed || mutationPending;
  const blockedReason = taskStateUnknown
    ? '任务状态尚未确认，暂时不能删除'
    : project.active_tasks.length > 0
      ? '项目仍有活跃任务，请先等待任务结束或取消任务'
      : undefined;
  const closeModal = () => {
    if (deleting) return;
    setOpen(false);
    setConfirmationName('');
  };

  return (
    <>
      {!hideTrigger ? (
        <Button
          type="link"
          danger
          size="small"
          icon={<DeleteOutlined />}
          disabled={triggerDisabled}
          loading={deleting}
          title={blockedReason}
          aria-label={`删除项目：${project.name}`}
          onClick={() => {
            setConfirmationName('');
            setOpen(true);
          }}
        >
          删除
        </Button>
      ) : null}
      <Modal
        title={`删除“${project.name}”？`}
        open={open}
        onCancel={closeModal}
        onOk={() => {
          if (deleteAllowed) onDelete();
        }}
        okText="删除项目"
        cancelText="取消"
        confirmLoading={deleting}
        okButtonProps={{ danger: true, disabled: !deleteAllowed }}
        cancelButtonProps={{ disabled: deleting }}
        closable={{ disabled: deleting }}
        keyboard={!deleting}
        mask={{ closable: !deleting }}
        destroyOnHidden
      >
        <Typography.Paragraph>
          项目关系和报告会被删除，历史任务转为独立任务；全局帖子与作者会保留。
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item
            label={`请输入完整项目名称以确认：${project.name}`}
            htmlFor={`project-delete-confirmation-${project.id}`}
            validateStatus={confirmationName && !confirmationMatches ? 'error' : undefined}
            help={
              confirmationName && !confirmationMatches
                ? '输入内容与项目名称不一致'
                : undefined
            }
          >
            <Input
              id={`project-delete-confirmation-${project.id}`}
              value={confirmationName}
              onChange={(event) => setConfirmationName(event.target.value)}
              autoComplete="off"
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
