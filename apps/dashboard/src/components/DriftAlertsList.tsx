import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DriftAlertItem } from "@/lib/types";

export function DriftAlertsList({ alerts }: { alerts: DriftAlertItem[] }) {
  if (alerts.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No drift alerts.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Type</TableHead>
          <TableHead>Metric</TableHead>
          <TableHead>Baseline → Current</TableHead>
          <TableHead>Delta</TableHead>
          <TableHead>Detail</TableHead>
          <TableHead>Detected</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.map((alert) => (
          <TableRow key={alert.id}>
            <TableCell>
              <Badge variant={alert.drift_type === "model" ? "default" : "secondary"}>
                {alert.drift_type}
              </Badge>
            </TableCell>
            <TableCell className="capitalize">{alert.metric_label.replace("_", " ")}</TableCell>
            <TableCell>
              {alert.baseline_value.toFixed(3)} → {alert.current_value.toFixed(3)}
            </TableCell>
            <TableCell className="text-destructive">{alert.delta.toFixed(3)}</TableCell>
            <TableCell className="max-w-md text-sm text-muted-foreground">
              {alert.detail}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {new Date(alert.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
