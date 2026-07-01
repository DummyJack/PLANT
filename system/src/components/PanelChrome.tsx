import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

interface PanelChromeProps {
  title: string;
  actions?: ReactNode;
  trailing?: ReactNode;
  subheader?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  centerTitle?: boolean;
  headerClassName?: string;
  titleGroupClassName?: string;
  titleClassName?: string;
}

export function PanelChrome({
  title,
  actions,
  trailing,
  subheader,
  children,
  className,
  bodyClassName,
  centerTitle = false,
  headerClassName,
  titleGroupClassName,
  titleClassName,
}: PanelChromeProps) {
  return (
    <div className={cn("card relative flex h-full min-w-0 flex-col overflow-hidden", className)}>
      <div className={cn("relative flex shrink-0 flex-wrap items-center gap-2 border-b border-gray-100 px-4 py-2.5", headerClassName)}>
        {centerTitle ? (
          <>
            <div className="flex min-w-0 flex-1 basis-24 items-center gap-2.5">
              {actions}
            </div>
            <span className={cn("section-title pointer-events-none absolute left-1/2 top-1/2 min-w-fit -translate-x-1/2 -translate-y-1/2 whitespace-nowrap text-center", titleClassName)}>
              {title}
            </span>
          </>
        ) : (
          <div className={cn("flex min-w-0 flex-1 basis-24 flex-wrap items-center gap-2.5", titleGroupClassName)}>
            <span className={cn("section-title shrink-0", titleClassName)}>{title}</span>
            {actions}
          </div>
        )}
        {trailing && (
          <div className="flex min-w-0 shrink-0 items-center justify-end gap-1.5">
            {trailing}
          </div>
        )}
      </div>
      {subheader}
      <div className={cn("min-h-0 flex-1 overflow-hidden", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
