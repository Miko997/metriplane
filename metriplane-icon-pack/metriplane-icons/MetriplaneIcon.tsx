import type { SVGProps } from "react";

export type MetriplaneIconName =
  | "camera-video"
  | "detect-markers"
  | "homography-calibration"
  | "metric-xy"
  | "multi-camera-fusion"
  | "zones-events"
  | "state-stream"
  | "replay-logs"
  | "observability-health"
  | "schema-first"
  | "integration-ready"
  | "object-tracking"
  | "coordinate-grid"
  | "calibration-target"
  | "websocket-json"
  | "health-monitor"
  | "dashboard-metrics"
  | "api-bridge"
  | "floor-state"
;

export function MetriplaneIcon({
  name,
  title,
  ...props
}: SVGProps<SVGSVGElement> & { name: MetriplaneIconName; title?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      color="currentColor"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <use href={`#mp-icon-${name}`} />
    </svg>
  );
}
