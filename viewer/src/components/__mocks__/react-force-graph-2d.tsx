import { forwardRef, useImperativeHandle } from 'react';

type ForceGraphMockProps = {
  graphData?: {
    nodes?: Array<Record<string, unknown>>;
    links?: Array<Record<string, unknown>>;
  };
  nodeLabel?: (node: Record<string, unknown>) => string;
  linkLabel?: (link: Record<string, unknown>) => string;
};

const ForceGraph2D = forwardRef<unknown, ForceGraphMockProps>(function ForceGraph2D(
  props,
  ref,
) {
  useImperativeHandle(ref, () => ({ zoomToFit: () => undefined }));
  const nodes = props.graphData?.nodes ?? [];
  const links = props.graphData?.links ?? [];
  return (
    <canvas
      data-testid="force-graph-2d"
      data-node-count={String(nodes.length)}
      data-link-count={String(links.length)}
    />
  );
});

export default ForceGraph2D;
export type ForceGraphMethods = {
  zoomToFit: () => void;
};
