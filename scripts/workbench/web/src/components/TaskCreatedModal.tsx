import { Button, Modal, Result } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { TaskReceipt } from '@/types';

const AUTO_STAY_SECONDS = 5;

export interface TaskCreatedModalProps {
  task: TaskReceipt | null;
  onStay: (task: TaskReceipt) => void;
  onView: (task: TaskReceipt) => void;
}

export default function TaskCreatedModal({ task, onStay, onView }: TaskCreatedModalProps) {
  const [seconds, setSeconds] = useState(AUTO_STAY_SECONDS);
  const onStayRef = useRef(onStay);

  useEffect(() => {
    onStayRef.current = onStay;
  }, [onStay]);

  useEffect(() => {
    if (!task) return;
    setSeconds(AUTO_STAY_SECONDS);
    const interval = window.setInterval(() => {
      setSeconds((current) => Math.max(0, current - 1));
    }, 1_000);
    const timeout = window.setTimeout(() => onStayRef.current(task), AUTO_STAY_SECONDS * 1_000);
    return () => {
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, [task]);

  if (!task) return null;

  return (
    <Modal
      title="任务已创建"
      open
      mask={{ closable: false }}
      onCancel={() => onStay(task)}
      footer={[
        <Button key="view" onClick={() => onView(task)}>
          查看任务详情
        </Button>,
        <Button key="stay" type="primary" autoFocus onClick={() => onStay(task)}>
          留在当前页（{seconds} 秒后自动）
        </Button>,
      ]}
      destroyOnHidden
      width={520}
    >
      <Result
        status="success"
        title="创建成功，任务已进入队列"
        subTitle={`${seconds} 秒后将自动留在当前页；如需查看进度，请选择“查看任务详情”。`}
        styles={{ root: { paddingInline: 0, paddingBottom: 8 } }}
      />
    </Modal>
  );
}
