import { useState, useRef, useCallback, useLayoutEffect, useMemo, type ReactNode } from 'react';

interface VirtualListProps<T> {
  items: ReadonlyArray<T>;
  itemHeight: number;
  renderItem: (item: T, index: number) => ReactNode;
  /** Optional stable key derivation. Falls back to index when omitted. */
  getKey?: (item: T, index: number) => string | number;
  overscan?: number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Lightweight virtual-scroll list.
 * Renders only visible items + overscan buffer for performance on large lists.
 */
export default function VirtualList<T>({
  items,
  itemHeight,
  renderItem,
  getKey,
  overscan = 8,
  className,
  style,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [clientHeight, setClientHeight] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setClientHeight(el.clientHeight);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setClientHeight(entry.contentRect.height);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (el) {
      setScrollTop(el.scrollTop);
      setClientHeight(el.clientHeight);
    }
  }, []);

  const totalHeight = items.length * itemHeight;

  const { startIndex, endIndex } = useMemo(() => {
    const rawStart = Math.floor(scrollTop / itemHeight);
    const rawEnd = Math.ceil((scrollTop + clientHeight) / itemHeight);
    return {
      startIndex: Math.max(0, rawStart - overscan),
      endIndex: Math.min(items.length, rawEnd + overscan),
    };
  }, [scrollTop, clientHeight, itemHeight, items.length, overscan]);

  const visibleItems = useMemo(() => {
    const nodes: ReactNode[] = [];
    for (let i = startIndex; i < endIndex; i++) {
      const item = items[i];
      const key = getKey ? getKey(item, i) : i;
      nodes.push(
        <div
          key={key}
          style={{
            position: 'absolute',
            top: 0,
            insetInline: 0,
            height: itemHeight,
            transform: `translateY(${i * itemHeight}px)`,
          }}
        >
          {renderItem(item, i)}
        </div>,
      );
    }
    return nodes;
  }, [startIndex, endIndex, items, itemHeight, renderItem, getKey]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className={className}
      style={{
        overflow: 'auto',
        position: 'relative',
        ...style,
      }}
    >
      <div style={{ height: totalHeight, position: 'relative' }}>
        {visibleItems}
      </div>
    </div>
  );
}
