import React from 'react';

interface WorkbenchBodyProps {
  leftPanel: React.ReactNode;
  rightPanel: React.ReactNode;
}

export default function WorkbenchBody({ leftPanel, rightPanel }: WorkbenchBodyProps) {
  return (
    <div className="flex-1 grid grid-cols-[60fr_40fr] gap-0 overflow-hidden h-full">
      {/* Left column */}
      <div className="overflow-y-auto border-r border-white/10 p-4">
        {leftPanel}
      </div>

      {/* Right column */}
      <div className="overflow-y-auto p-4 flex flex-col gap-4">
        {rightPanel}
      </div>
    </div>
  );
}
