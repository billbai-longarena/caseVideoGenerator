import type {
  NetworkLayoutMode,
  NetworkLink,
  NetworkNode,
} from "../../../data/types";

export type ResolvedNetworkLayoutMode = Exclude<NetworkLayoutMode, "auto">;

export type NetworkNodeBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type NetworkLayoutResult = {
  mode: ResolvedNetworkLayoutMode;
  compact: boolean;
  headerHeight: number;
  nodeWidth: number;
  nodeHeight: number;
  positions: Map<string, NetworkNodeBox>;
};

type LayoutInput = {
  nodes: NetworkNode[];
  links: NetworkLink[];
  width: number;
  height: number;
  label?: string;
  requested?: NetworkLayoutMode;
};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));

const distributedStarts = (
  count: number,
  start: number,
  available: number,
  itemSize: number,
) => {
  if (count <= 1) return [start + (available - itemSize) / 2];
  const travel = Math.max(0, available - itemSize);
  return Array.from({length: count}, (_, index) => start + (travel * index) / (count - 1));
};

const nodeDegrees = (nodes: NetworkNode[], links: NetworkLink[]) => {
  const degrees = new Map(nodes.map((node) => [node.id, 0]));
  for (const link of links) {
    if (degrees.has(link.from)) degrees.set(link.from, (degrees.get(link.from) ?? 0) + 1);
    if (degrees.has(link.to)) degrees.set(link.to, (degrees.get(link.to) ?? 0) + 1);
  }
  return degrees;
};

const selectHub = (nodes: NetworkNode[], links: NetworkLink[]) => {
  const degrees = nodeDegrees(nodes, links);
  return [...nodes].sort((left, right) => {
    const emphasisDelta = Number(Boolean(right.emphasis)) - Number(Boolean(left.emphasis));
    if (emphasisDelta !== 0) return emphasisDelta;
    return (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0);
  })[0]?.id;
};

const autoHub = (nodes: NetworkNode[], links: NetworkLink[]) => {
  if (nodes.length < 3) return undefined;
  const degrees = nodeDegrees(nodes, links);
  const maximum = Math.max(...nodes.map((node) => degrees.get(node.id) ?? 0));
  if (maximum < nodes.length - 1) return undefined;
  const candidates = nodes.filter((node) => (degrees.get(node.id) ?? 0) === maximum);
  if (candidates.length === 1) return candidates[0].id;
  const emphasized = candidates.filter((node) => node.emphasis);
  return emphasized.length === 1 ? emphasized[0].id : undefined;
};

const resolveMode = ({
  nodes,
  links,
  width,
  height,
  requested = "auto",
}: LayoutInput): {mode: ResolvedNetworkLayoutMode; hubId?: string} => {
  if (requested !== "auto") {
    return {
      mode: requested,
      hubId: requested === "hub" ? selectHub(nodes, links) : undefined,
    };
  }

  const shallow = height <= 280 || width / Math.max(1, height) >= 3.1;
  if (shallow) return {mode: "row"};
  if (nodes.length <= 2) {
    return {mode: width >= height * 0.72 ? "row" : "column"};
  }

  const hubId = autoHub(nodes, links);
  if (hubId) return {mode: "hub", hubId};
  if (nodes.length === 3) return {mode: "triangle"};
  return {mode: "grid"};
};

const boxesFromPositions = (
  nodes: NetworkNode[],
  positions: Array<{x: number; y: number}>,
  nodeWidth: number,
  nodeHeight: number,
) =>
  new Map(
    nodes.map((node, index) => [
      node.id,
      {
        x: positions[index]?.x ?? 0,
        y: positions[index]?.y ?? 0,
        width: nodeWidth,
        height: nodeHeight,
      },
    ]),
  );

export const resolveNetworkLayout = (input: LayoutInput): NetworkLayoutResult => {
  const {nodes, links, width, height, label} = input;
  const compact = height <= 280;
  const headerHeight = label ? (compact ? 38 : 58) : 0;
  const horizontalPadding = compact ? 14 : width < 650 ? 20 : 34;
  const topGap = label ? (compact ? 8 : 18) : compact ? 8 : 16;
  const bottomPadding = compact ? 8 : 22;
  const area = {
    x: horizontalPadding,
    y: headerHeight + topGap,
    width: Math.max(100, width - horizontalPadding * 2),
    height: Math.max(72, height - headerHeight - topGap - bottomPadding),
  };
  const {mode, hubId: autoHubId} = resolveMode(input);
  const hasLinkLabels = links.some((link) => Boolean(link.label));

  if (mode === "row") {
    const gap = hasLinkLabels ? (compact ? 78 : 96) : compact ? 34 : 48;
    const nodeWidth = clamp(
      (area.width - gap * Math.max(0, nodes.length - 1)) / Math.max(1, nodes.length),
      96,
      compact ? 310 : 340,
    );
    const nodeHeight = clamp(area.height, 76, compact ? 104 : 146);
    const groupWidth = nodeWidth * nodes.length + gap * Math.max(0, nodes.length - 1);
    const startX = area.x + (area.width - groupWidth) / 2;
    const y = area.y + (area.height - nodeHeight) / 2;
    return {
      mode,
      compact,
      headerHeight,
      nodeWidth,
      nodeHeight,
      positions: boxesFromPositions(
        nodes,
        nodes.map((_, index) => ({x: startX + index * (nodeWidth + gap), y})),
        nodeWidth,
        nodeHeight,
      ),
    };
  }

  if (mode === "column") {
    const gap = hasLinkLabels ? 62 : 26;
    const nodeWidth = clamp(area.width, 120, 340);
    const nodeHeight = clamp(
      (area.height - gap * Math.max(0, nodes.length - 1)) / Math.max(1, nodes.length),
      72,
      138,
    );
    const groupHeight = nodeHeight * nodes.length + gap * Math.max(0, nodes.length - 1);
    const x = area.x + (area.width - nodeWidth) / 2;
    const startY = area.y + (area.height - groupHeight) / 2;
    return {
      mode,
      compact,
      headerHeight,
      nodeWidth,
      nodeHeight,
      positions: boxesFromPositions(
        nodes,
        nodes.map((_, index) => ({x, y: startY + index * (nodeHeight + gap)})),
        nodeWidth,
        nodeHeight,
      ),
    };
  }

  if (mode === "triangle") {
    const horizontalGap = hasLinkLabels ? 112 : 68;
    const verticalGap = hasLinkLabels ? 76 : 50;
    const nodeWidth = clamp((area.width - horizontalGap) / 2, 120, 310);
    const nodeHeight = clamp((area.height - verticalGap) / 2, 82, 142);
    const lowerWidth = nodeWidth * 2 + horizontalGap;
    const lowerStartX = area.x + (area.width - lowerWidth) / 2;
    const topY = area.y;
    const bottomY = area.y + area.height - nodeHeight;
    return {
      mode,
      compact,
      headerHeight,
      nodeWidth,
      nodeHeight,
      positions: boxesFromPositions(
        nodes,
        [
          {x: area.x + (area.width - nodeWidth) / 2, y: topY},
          {x: lowerStartX, y: bottomY},
          {x: lowerStartX + nodeWidth + horizontalGap, y: bottomY},
        ],
        nodeWidth,
        nodeHeight,
      ),
    };
  }

  if (mode === "hub") {
    const hubId = autoHubId ?? selectHub(nodes, links) ?? nodes[0]?.id;
    const hub = nodes.find((node) => node.id === hubId) ?? nodes[0];
    const leaves = nodes.filter((node) => node.id !== hub?.id);
    const landscape = area.width / Math.max(1, area.height) >= 1.32;

    if (landscape) {
      const horizontalGap = hasLinkLabels ? 132 : 88;
      const nodeWidth = clamp((area.width - horizontalGap) / 2, 120, 330);
      const leafGap = leaves.length >= 3 ? 22 : 42;
      const nodeHeight = clamp(
        (area.height - leafGap * Math.max(0, leaves.length - 1)) / Math.max(1, leaves.length),
        82,
        142,
      );
      const groupWidth = nodeWidth * 2 + horizontalGap;
      const leftX = area.x + (area.width - groupWidth) / 2;
      const rightX = leftX + nodeWidth + horizontalGap;
      const leafYs = distributedStarts(leaves.length, area.y, area.height, nodeHeight);
      const boxes = new Map<string, NetworkNodeBox>();
      leaves.forEach((node, index) => {
        boxes.set(node.id, {x: leftX, y: leafYs[index], width: nodeWidth, height: nodeHeight});
      });
      if (hub) {
        boxes.set(hub.id, {
          x: rightX,
          y: area.y + (area.height - nodeHeight) / 2,
          width: nodeWidth,
          height: nodeHeight,
        });
      }
      return {mode, compact, headerHeight, nodeWidth, nodeHeight, positions: boxes};
    }

    const horizontalGap = leaves.length >= 3 ? 24 : 54;
    const verticalGap = hasLinkLabels ? 84 : 58;
    const nodeWidth = clamp(
      (area.width - horizontalGap * Math.max(0, leaves.length - 1)) / Math.max(1, leaves.length),
      112,
      leaves.length >= 3 ? 238 : 290,
    );
    const nodeHeight = clamp((area.height - verticalGap) / 2, 82, 136);
    const topWidth = nodeWidth * leaves.length + horizontalGap * Math.max(0, leaves.length - 1);
    const topStartX = area.x + (area.width - topWidth) / 2;
    const boxes = new Map<string, NetworkNodeBox>();
    leaves.forEach((node, index) => {
      boxes.set(node.id, {
        x: topStartX + index * (nodeWidth + horizontalGap),
        y: area.y,
        width: nodeWidth,
        height: nodeHeight,
      });
    });
    if (hub) {
      boxes.set(hub.id, {
        x: area.x + (area.width - nodeWidth) / 2,
        y: area.y + area.height - nodeHeight,
        width: nodeWidth,
        height: nodeHeight,
      });
    }
    return {mode, compact, headerHeight, nodeWidth, nodeHeight, positions: boxes};
  }

  const columns = nodes.length <= 2 ? nodes.length : 2;
  const rows = Math.ceil(nodes.length / Math.max(1, columns));
  const horizontalGap = hasLinkLabels ? 104 : 54;
  const verticalGap = hasLinkLabels ? 76 : 48;
  const nodeWidth = clamp(
    (area.width - horizontalGap * Math.max(0, columns - 1)) / Math.max(1, columns),
    112,
    310,
  );
  const nodeHeight = clamp(
    (area.height - verticalGap * Math.max(0, rows - 1)) / Math.max(1, rows),
    80,
    142,
  );
  const gridWidth = nodeWidth * columns + horizontalGap * Math.max(0, columns - 1);
  const gridHeight = nodeHeight * rows + verticalGap * Math.max(0, rows - 1);
  const startX = area.x + (area.width - gridWidth) / 2;
  const startY = area.y + (area.height - gridHeight) / 2;
  return {
    mode: "grid",
    compact,
    headerHeight,
    nodeWidth,
    nodeHeight,
    positions: boxesFromPositions(
      nodes,
      nodes.map((_, index) => ({
        x: startX + (index % columns) * (nodeWidth + horizontalGap),
        y: startY + Math.floor(index / columns) * (nodeHeight + verticalGap),
      })),
      nodeWidth,
      nodeHeight,
    ),
  };
};
