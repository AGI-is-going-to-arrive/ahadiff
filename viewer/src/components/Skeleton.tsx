import './Skeleton.css';

type SkeletonVariant = 'text' | 'text-short' | 'card' | 'chart' | 'row' | 'circle';

interface SkeletonProps {
  variant?: SkeletonVariant;
  width?: string;
  height?: string;
  className?: string;
}

export default function Skeleton({ variant = 'text', width, height, className }: SkeletonProps) {
  return (
    <div
      className={`skeleton skeleton--${variant}${className ? ` ${className}` : ''}`}
      style={{ width, height }}
      role="presentation"
      aria-hidden="true"
    />
  );
}

interface SkeletonGroupProps {
  count: number;
  variant?: SkeletonVariant;
  className?: string;
}

export function SkeletonGroup({ count, variant = 'row', className }: SkeletonGroupProps) {
  return (
    <div className={`skeleton-group${className ? ` ${className}` : ''}`}>
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} variant={variant} />
      ))}
    </div>
  );
}
