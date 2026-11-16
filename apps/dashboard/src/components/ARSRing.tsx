import { PolarAngleAxis, RadialBar, RadialBarChart } from "recharts";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { arsHex } from "@/lib/utils";

/** 270-degree radial gauge of an ARS value (0..1) with a count-up centre label. */
export function ARSRing({ ars, size = 96 }: { ars: number | null | undefined; size?: number }) {
  const color = arsHex(ars);
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <RadialBarChart
        width={size}
        height={size}
        innerRadius="76%"
        outerRadius="100%"
        data={[{ v: (ars ?? 0) * 100 }]}
        startAngle={225}
        endAngle={-45}
      >
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} angleAxisId={0} />
        <RadialBar
          dataKey="v"
          angleAxisId={0}
          cornerRadius={8}
          fill={color}
          background={{ fill: "hsl(var(--muted))" }}
          isAnimationActive
          animationDuration={900}
        />
      </RadialBarChart>
      <div
        className="absolute inset-0 flex items-center justify-center text-xl font-bold tabular-nums"
        style={{ color }}
      >
        {ars == null ? "—" : <AnimatedNumber value={ars} decimals={2} duration={0.9} />}
      </div>
    </div>
  );
}
