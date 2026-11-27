'use client';

import { MessageSquare } from 'lucide-react';

export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
      <div className="flex items-center justify-center w-16 h-16 rounded-full bg-muted mb-4">
        <MessageSquare className="h-8 w-8" />
      </div>
      <h3 className="text-lg font-medium text-foreground">暂无对话</h3>
      <p className="text-sm">选择一个知识库或发送一条消息开始对话</p>
    </div>
  );
}
